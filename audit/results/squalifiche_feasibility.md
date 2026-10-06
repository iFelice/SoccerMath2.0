# Fattibilita' feature squalifiche — eventi certi, validazione, conteggi, potenza

**STATO ARTIFACT PLAYER_MATCH:** id `11415875090`, nome `ppda-player-verify-37461010400` da run `37461010400`, dimensione compressa `10030865` byte, creato `2026-10-06T12:51:23Z`, scadenza `2026-10-20T12:51:20Z`, expired=`false`. Scade entro 30 giorni rispetto al 2026-10-06: **SI**. I JSON raw restano fuori git; le istruzioni riproducibili di rigenerazione sono nella sezione 1.

Generato: `2026-10-06T15:56:13+00:00` UTC. Commit base script: `95c9b59b8a73fbd2b55b4f018e9a5248c352a0f9`.

## 0. Evidenze comandi
| Esito | Comando | Evidenza |
|---|---|---|
| OK | gh run list --workflow ppda_player_verify.yml | run recupero fresco 37461010400 workflow Verifica PPDA/deep/giocatore |
| OK | gh api repos/iFelice/SoccerMath2.0/actions/runs/<run>/artifacts | artifact id=11415875090 name=ppda-player-verify-37461010400 size=10030865 created=2026-10-06T12:51:23Z expires=2026-10-20T12:51:20Z expired=false |
| NON OK | gh run download 34992936842 --name ppda-player-verify-34992936842 | no valid artifacts found to download; API run artifacts total_count=0 (artifact PR#23 non piu' presente) |
| NON OK | gh run download 37461010400 --name ppda-player-verify-37461010400 | sandbox: Azure blob productionresultssa1.blob.core.windows.net -> EOF; download riuscito dentro GitHub Actions per l'analisi |
| NON OK | python update_all_ppda_player_db.py ... (sandbox) | sandbox: GitHub release asset TLS client e understat.com chiudono TLS (SSL_ERROR_SYSCALL/EOF); acquisizione reale riuscita nel runner Actions del run 37461010400 |
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

### Rigenerazione, non conservazione permanente
Usare il workflow versionato `.github/workflows/ppda_player_verify.yml` (`Verifica PPDA/deep/giocatore (sola lettura)`): GitHub → Actions → workflow → **Run workflow**, selezionare il branch e lasciare vuoti `seasons`, `player_seasons` e `sample_matches_per_league` per la finestra mobile completa; in alternativa `gh workflow run ppda_player_verify.yml --ref <branch>` con credenziali che autorizzino `workflow_dispatch`. Lo step `Acquisizione reale (Understat, 5 leghe)` esegue `update_all_ppda_player_db.py`; al termine scaricare l'artifact `ppda-player-verify-<run_id>` e usare `database/player_match_*.json`. Il run osservato 37461010400 e' durato 44m08s (12:07:18–12:51:26 UTC), artifact compresso 10,030,865 byte; durata e dimensione possono variare con la finestra mobile.
Confronto PR #23: snapshot storico documentato **224902** righe (~225k); rigenerazione **226657** righe, differenza **+1755** (+0.78%). Copertura invariata nel perimetro: 5 leghe e 5 stagioni 2022–2026; il numero di partite/righe aggiornato e' nella tabella sopra.

Regole applicate: Serie A: gialli cumulativi 5,9,13,16,18, poi ogni ammonizione; coppe separate; Premier League: 5 gialli entro 19a partita squadra -> 1; 10 entro 32a -> 2; 15 -> 3; La Liga: cicli da 5; esenzione ultima giornata; doppia ammonizione esclusa/ambigua; Bundesliga: 5a, 10a, 15a... ammonizione -> 1 turno; Ligue 1: 2023/24-2024/25: 3 gialli in 10 incontri ufficiali; 2025/26: 5 gialli; coppe nazionali mancanti nel dataset

Limiti dichiarati: rosso diretto certo contato solo quando `red_cards>0` e `yellow_cards==0`; casi red+yellow esclusi come ambigui; Ligue 1 usa dato league-only e dichiara coppe nazionali mancanti; nessuna ground truth ufficiale versionata, validazione minima presenza/assenza su player_match.

## 2. Eventi certi ricostruiti
| Lega | Stagione | Eventi certi | High usage 60% | High usage 40% | Violazioni known_at<kickoff |
|---|---|---|---|---|---|
| Serie A | 2023/24 | 192 | 145 | 172 | 0 |
| Serie A | 2024/25 | 159 | 105 | 131 | 0 |
| Serie A | 2025/26 | 150 | 112 | 125 | 0 |
| Premier League | 2023/24 | 101 | 77 | 87 | 0 |
| Premier League | 2024/25 | 93 | 65 | 80 | 0 |
| Premier League | 2025/26 | 62 | 47 | 54 | 0 |
| La Liga | 2023/24 | 205 | 140 | 174 | 0 |
| La Liga | 2024/25 | 201 | 140 | 169 | 0 |
| La Liga | 2025/26 | 206 | 136 | 173 | 0 |
| Bundesliga | 2023/24 | 158 | 128 | 142 | 0 |
| Bundesliga | 2024/25 | 122 | 91 | 103 | 0 |
| Bundesliga | 2025/26 | 116 | 87 | 100 | 0 |
| Ligue 1 | 2023/24 | 93 | 64 | 76 | 0 |
| Ligue 1 | 2024/25 | 85 | 48 | 64 | 0 |
| Ligue 1 | 2025/26 | 83 | 51 | 60 | 0 |

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

### 3.1 Falsi positivi della ricostruzione
Precisione operativa della regola pre-partita = confermati / (confermati + casi poi osservati in campo). Il termine 'confermato' indica qui soltanto la non-presenza nel player_match successivo, non una ground truth ufficiale.
| Lega | Confermati | Osservati in campo | Precisione |
|---|---|---|---|
| Serie A | 501 | 66 | 88.4% |
| Premier League | 256 | 18 | 93.4% |
| La Liga | 612 | 56 | 91.6% |
| Bundesliga | 396 | 13 | 96.8% |
| Ligue 1 | 261 | 282 | 48.1% |

Campione casuale semplice di 30/435, seed Python `random.Random(3300435)`, estratto dopo ordinamento stabile. La classificazione e' diagnostica: usa lega, regola e record player_match; senza provvedimenti ufficiali la causa individuale non e' verificabile in senso forense.
| Causa | Conteggio nel campione |
|---|---|
| cartellino di coppa contato o non contato | 11 |
| soglia o azzeramento di diffida sbagliato | 18 |
| ricorso o condono | 1 |
| errore di identità del giocatore | 0 |
| altro | 0 |
| Lega | Stagione | Giocatore | Match origine | Match previsto | Causa | Base classificazione |
|---|---|---|---|---|---|---|
| Serie A | 2023/24 | Amir Rrahmani | 22636 | 22654 | soglia o azzeramento di diffida sbagliato | trigger da accumulo league-only seguito da presenza nella gara prevista |
| Ligue 1 | 2025/26 | Marvin Senaya | 29747 | 29754 | soglia o azzeramento di diffida sbagliato | trigger da accumulo league-only seguito da presenza nella gara prevista |
| La Liga | 2024/25 | Isi Palazón | 27329 | 27336 | soglia o azzeramento di diffida sbagliato | trigger da accumulo league-only seguito da presenza nella gara prevista |
| Serie A | 2023/24 | Remo Freuler | 22630 | 22642 | soglia o azzeramento di diffida sbagliato | trigger da accumulo league-only seguito da presenza nella gara prevista |
| Ligue 1 | 2023/24 | Frank Magri | 23459 | 23463 | cartellino di coppa contato o non contato | regola su incontri ufficiali, ma input disponibile solo per il campionato |
| Ligue 1 | 2023/24 | Marvin Senaya | 23602 | 23605 | cartellino di coppa contato o non contato | regola su incontri ufficiali, ma input disponibile solo per il campionato |
| La Liga | 2023/24 | Aitor Paredes | 22996 | 23011 | soglia o azzeramento di diffida sbagliato | trigger da accumulo league-only seguito da presenza nella gara prevista |
| Ligue 1 | 2024/25 | Neil El Aynaoui | 28289 | 28296 | cartellino di coppa contato o non contato | regola su incontri ufficiali, ma input disponibile solo per il campionato |
| Ligue 1 | 2025/26 | Simon Ebonog | 29745 | 29755 | soglia o azzeramento di diffida sbagliato | trigger da accumulo league-only seguito da presenza nella gara prevista |
| Serie A | 2024/25 | Nicolo Rovella | 27559 | 27566 | soglia o azzeramento di diffida sbagliato | trigger da accumulo league-only seguito da presenza nella gara prevista |
| Ligue 1 | 2025/26 | Tylel Tati | 29695 | 29706 | soglia o azzeramento di diffida sbagliato | trigger da accumulo league-only seguito da presenza nella gara prevista |
| Ligue 1 | 2025/26 | Pierre Lees-Melou | 29785 | 29796 | soglia o azzeramento di diffida sbagliato | trigger da accumulo league-only seguito da presenza nella gara prevista |
| Ligue 1 | 2024/25 | Mitchel Bakker | 28280 | 28289 | cartellino di coppa contato o non contato | regola su incontri ufficiali, ma input disponibile solo per il campionato |
| La Liga | 2024/25 | Ladislav Krejcí | 27166 | 27173 | soglia o azzeramento di diffida sbagliato | trigger da accumulo league-only seguito da presenza nella gara prevista |
| Ligue 1 | 2023/24 | Formose Mendy | 23621 | 23635 | cartellino di coppa contato o non contato | regola su incontri ufficiali, ma input disponibile solo per il campionato |
| Ligue 1 | 2024/25 | Guela Doué | 28093 | 28110 | cartellino di coppa contato o non contato | regola su incontri ufficiali, ma input disponibile solo per il campionato |
| Ligue 1 | 2024/25 | Brendan Chardonnet | 28325 | 28333 | cartellino di coppa contato o non contato | regola su incontri ufficiali, ma input disponibile solo per il campionato |
| La Liga | 2024/25 | Omar El Hilali | 27261 | 27262 | soglia o azzeramento di diffida sbagliato | trigger da accumulo league-only seguito da presenza nella gara prevista |
| Ligue 1 | 2024/25 | Alexsandro Ribeiro | 28111 | 28120 | cartellino di coppa contato o non contato | regola su incontri ufficiali, ma input disponibile solo per il campionato |
| Serie A | 2024/25 | Armando Izzo | 27589 | 27601 | soglia o azzeramento di diffida sbagliato | trigger da accumulo league-only seguito da presenza nella gara prevista |
| Serie A | 2025/26 | Fikayo Tomori | 30141 | 30149 | soglia o azzeramento di diffida sbagliato | trigger da accumulo league-only seguito da presenza nella gara prevista |
| Premier League | 2024/25 | Christian Nørgaard | 26715 | 26722 | ricorso o condono | rosso osservato ma presenza successiva; senza giudice sportivo la distinzione da altra causa non e' verificabile |
| Serie A | 2024/25 | Pedro Pereira | 27692 | 27708 | soglia o azzeramento di diffida sbagliato | trigger da accumulo league-only seguito da presenza nella gara prevista |
| Ligue 1 | 2023/24 | Thomas Foket | 23521 | 23526 | cartellino di coppa contato o non contato | regola su incontri ufficiali, ma input disponibile solo per il campionato |
| Ligue 1 | 2025/26 | Florian Thauvin | 29704 | 29710 | soglia o azzeramento di diffida sbagliato | trigger da accumulo league-only seguito da presenza nella gara prevista |
| Ligue 1 | 2023/24 | Formose Mendy | 23500 | 23508 | cartellino di coppa contato o non contato | regola su incontri ufficiali, ma input disponibile solo per il campionato |
| Bundesliga | 2024/25 | Magnus Knudsen | 27903 | 27910 | soglia o azzeramento di diffida sbagliato | trigger da accumulo league-only seguito da presenza nella gara prevista |
| Ligue 1 | 2024/25 | Cédric Kipré | 28223 | 28234 | cartellino di coppa contato o non contato | regola su incontri ufficiali, ma input disponibile solo per il campionato |
| La Liga | 2025/26 | Lucien Agoume | 29480 | 29476 | soglia o azzeramento di diffida sbagliato | trigger da accumulo league-only seguito da presenza nella gara prevista |
| Ligue 1 | 2025/26 | Dayann Methalie | 29727 | 29744 | soglia o azzeramento di diffida sbagliato | trigger da accumulo league-only seguito da presenza nella gara prevista |

**Leakage esplicito:** il filtro `il giocatore ha giocato la partita saltata` usa informazioni successive al pronostico. Un eventuale modello futuro deve usare la lista pre-partita **NON filtrata**; la lista filtrata serve soltanto alla stima di fattibilita'/validazione retrospettiva.

## 4-5. Alto utilizzo e conteggi
Alto utilizzo = minuti giocati >=60% dei 450 minuti disponibili nelle ultime 5 partite di campionato della squadra prima della partita saltata; sensibilita' 40% calcolata negli output macchina.
| Lega | Stagione | Partite con >=1 squalificato | Partite con >=1 high60 | Partite con >=1 high40 | Ruoli eventi | Partite multi-assenti | Da entrambe le parti | Squadre | Giocatori |
|---|---|---|---|---|---|---|---|---|---|
| Serie A | 2023/24 | 144 | 119 | 134 | portiere:2, difensore:84, centrocampista:68, attaccante:17, non disponibile:21 | 38 | 28 | 20 | 167 |
| Serie A | 2024/25 | 135 | 93 | 114 | portiere:1, difensore:73, centrocampista:46, attaccante:10, non disponibile:29 | 21 | 9 | 20 | 146 |
| Serie A | 2025/26 | 119 | 94 | 103 | portiere:3, difensore:72, centrocampista:39, attaccante:17, non disponibile:19 | 26 | 13 | 20 | 136 |
| Premier League | 2023/24 | 82 | 63 | 70 | portiere:0, difensore:40, centrocampista:41, attaccante:8, non disponibile:12 | 18 | 7 | 20 | 85 |
| Premier League | 2024/25 | 81 | 58 | 73 | portiere:0, difensore:33, centrocampista:43, attaccante:3, non disponibile:14 | 10 | 3 | 19 | 81 |
| Premier League | 2025/26 | 56 | 45 | 50 | portiere:0, difensore:31, centrocampista:21, attaccante:3, non disponibile:7 | 5 | 0 | 19 | 53 |
| La Liga | 2023/24 | 150 | 113 | 129 | portiere:4, difensore:84, centrocampista:70, attaccante:19, non disponibile:28 | 43 | 20 | 20 | 165 |
| La Liga | 2024/25 | 152 | 115 | 134 | portiere:5, difensore:80, centrocampista:63, attaccante:15, non disponibile:38 | 38 | 16 | 20 | 155 |
| La Liga | 2025/26 | 153 | 108 | 132 | portiere:2, difensore:93, centrocampista:62, attaccante:9, non disponibile:40 | 44 | 24 | 20 | 164 |
| Bundesliga | 2023/24 | 115 | 100 | 108 | portiere:1, difensore:73, centrocampista:64, attaccante:7, non disponibile:13 | 36 | 16 | 18 | 136 |
| Bundesliga | 2024/25 | 99 | 78 | 86 | portiere:2, difensore:55, centrocampista:38, attaccante:11, non disponibile:16 | 22 | 12 | 18 | 101 |
| Bundesliga | 2025/26 | 97 | 77 | 88 | portiere:1, difensore:53, centrocampista:38, attaccante:4, non disponibile:20 | 17 | 12 | 18 | 97 |
| Ligue 1 | 2023/24 | 80 | 56 | 67 | portiere:2, difensore:46, centrocampista:23, attaccante:9, non disponibile:13 | 13 | 9 | 18 | 79 |
| Ligue 1 | 2024/25 | 72 | 42 | 56 | portiere:0, difensore:42, centrocampista:19, attaccante:6, non disponibile:18 | 12 | 8 | 18 | 77 |
| Ligue 1 | 2025/26 | 73 | 46 | 54 | portiere:3, difensore:49, centrocampista:21, attaccante:4, non disponibile:6 | 10 | 5 | 18 | 75 |

## 6. Potenza statistica
A) 1X2: shock transitorio sul differenziale Elo `d_match=d+Δ_H−Δ_A`, qui Δ effettivo = `δ*(away_high-home_high)`. Stima δ via griglia e test ΔLogLoss appaiato con bootstrap a blocchi squadra.
| δ vero | Potenza α=5% |
|---|---|
| 15 | 26.2% |
| 30 | 72.5% |
| 50 | 100.0% |
Potenza esatta alla prior centrale δ=30 Elo: **72.5%**. MDE 80% A: `50` punti Elo. Sd posterior: **9.50 punti Elo**; rapporto sd posterior/prior: `0.317`. Stima puntuale esplorativa sui risultati reali: **δ̂=16.5 Elo**.

B) Totali: shock log-lambda: attaccante assente -> lambda propria; portiere/difensore assente -> lambda avversaria. Centrocampisti esclusi dallo shock B e conteggiati nei ruoli.
| δ vero | Potenza α=5% |
|---|---|
| 0.05 | 10.0% |
| 0.1 | 41.2% |
| 0.15 | 80.0% |
Potenza esatta alla prior centrale δ=0.10 log-lambda: **41.2%**. MDE 80% B: `0.15` log-lambda. Sd posterior: **0.0433 log-lambda**; rapporto sd posterior/prior: `0.433`. Stima puntuale esplorativa sui risultati reali: **δ̂=0.004 log-lambda**.

### Sensibilita' sulla lista pre-partita non filtrata
Il modello/test usa tutti i 2.461 candidati pre-partita come esposizione osservata; nella simulazione l'effetto vero e' imposto soltanto sui 2.026 eventi confermati. I 435 falsi positivi hanno effetto vero zero. Questa e' la specifica utilizzabile senza leakage al momento del pronostico.
| Punto | δ vero | Potenza α=5% |
|---|---|---|
| A 1X2 | 15 | 25.0% |
| A 1X2 | 30 | 63.7% |
| A 1X2 | 50 | 98.8% |
| B Totali | 0.05 | 7.5% |
| B Totali | 0.1 | 26.2% |
| B Totali | 0.15 | 70.0% |
Sensibilita' A: MDE 80% `50` Elo. Sensibilita' B: MDE 80% `>0.15` log-lambda. Il verdetto formale sotto resta quello della regola fissata sull'analisi principale.

## 7-8. Prior e verdetto
| Punto | Prior | Regola GO | MDE | posterior/prior | Verdetto |
|---|---|---|---|---|---|
| A 1X2 | N(0,30^2) Elo | MDE<=30 e ratio<=0.7 | 50 | 0.317 | NO-GO |
| B Totali | N(0,0.10^2) | MDE<=0.10 e ratio<=0.7 | 0.15 | 0.433 | NO-GO |

Entrambi NO-GO: pista da mantenere in raccolta prospettica/validazione ground truth; non e' un effetto negativo.

## Chiusura
Report generato con dati player_match recuperati dall'artifact GitHub Actions; il precedente referto non basato su artifact e' sostituito.
