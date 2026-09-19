# Parte B (rediretta): fattibilita' "sapere chi manca di certo e quanto vale" — sospensioni, convocazioni, infortuni, proxy di valore

Referto del `2026-09-20`. La Parte B viene **rediretta**: non piu' "prevedere la formazione", ma **"sapere chi manca di certo e quanto vale"**. Ancora **sola fattibilita' dei dati, nessun codice di produzione**: le verifiche richieste sono state condotte sul sorgente pinnato di `soccerdata==1.9.1`, sull'archivio `player_match` definito dalla pipeline della PR #23 (merge 2026-09-16) e su fonti pubbliche/regolamenti, senza nuove acquisizioni dati.

## 1. Sintesi del verdetto

| Pezzo | Fattibile? | Storico 2022/23→2025/26 | Fonte |
|---|---|---|---|
| Squalifiche da accumulo cartellini | **Si', ricostruzione deterministica** (regole pubbliche, stabili nel periodo, una variazione a meta' finestra per la Ligue 1) | ricostruibile dai cartellini gia' in archivio | `player_match` (PR #23) + regolamenti §2 |
| Squalifiche da rosso diretto | **Parziale**: l'assenza alla giornata successiva e' certa, la durata oltre la prima no (decide l'organo disciplinare) | come sopra, durata = incognita | idem |
| Infortuni pre-match | **Si' prospettico; storico plausibile** per tutta la finestra | plausibile (evidenza documentale fino al 2021; campionamento nel perimetro §6) | WhoScored via soccerdata §4 |
| Convocazioni nazionali per finestra | **No** per le finestre ordinarie (nessun archivio pubblico stabile); si' solo per i tornei finali (Mondiali/Europei) | solo tornei finali | FIFA/UEFA/openfootball §3 |
| Valore dell'assente (proxy semplice) | **Si', la pipeline PR #23 basta cosi' com'e'** per proxy offensivi dei giocatori di movimento; portieri e difensori puri richiedono un proxy diverso (dichiarato) | gia' acquisito 100% | `player_match` §5 |

## 2. Squalifiche: regole per lega e casi noti verificati

Le regole sono pubbliche, per competizione, e nel periodo 2022/23→2026/27 sono **stabili tranne un caso** (Ligue 1):

| Lega | Regola accumulo gialli (campionato) | Cicli | Note |
|---|---|---|---|
| Serie A | 5a ammonizione → 1 giornata (art. 19 c.9 CGS, in vigore dal 2015/16) | progressivi: 5, poi 5, 4, 3, 2, poi ogni giallo (dal 19° in poi ogni ammonizione squalifica) — schema confermato da piu' fonti ma la sequenza esatta dei cicli successivi va ricontrollata sul testo CGS vigente prima dell'implementazione | cartellini di Coppa Italia/Europa non comunicanti con la Serie A |
| Premier League | 5 gialli nelle **prime 19 partite** di campionato della squadra → 1 giornata; 10 gialli **entro la 32a** → 2 giornate; 15 gialli in stagione → 3 giornate | soglia dipendente dall'ordine temporale delle partite (serve il calendario, che c'e') | dal 2018/19 i gialli valgono solo per competizione; i rossi invece si scontano in tutte le competizioni domestiche |
| La Liga | 5 gialli nella stessa stagione/competizione → 1 giornata; ciclo nuovo dopo la squalifica (art. 112 Codigo Disciplinario RFEF) | uniforme (5, 5, 5...) | la 5a gialla presa all'ultima giornata non si trascina alla stagione successiva; doppia ammonizione nello stesso match: i due gialli NON contano per il ciclo |
| Bundesliga | 5a gialla → 1 giornata; poi ogni altre 5 (10a, 15a...) | uniforme | conteggio per competizione (Pokal separato); reset a fine stagione |
| Ligue 1 | **fino al 2024/25**: 3 ammonizioni in una finestra di 10 incontri ufficiali → 1 giornata; **dal 2025/26**: regola "a 5 gialli" come le altre leghe (riforma LFP adottata il 3/6/2025) | finestra mobile 10 partite → poi ciclo uniforme | il cambio regola cade DENTRO la finestra di backtest: il motore deve essere season-aware |

Cosa e' deterministico e cosa no:
- **deterministico**: squalifiche per accumulo (tutte e 5 le leghe, con le regole sopra) e espulsione per doppia ammonizione (1 giornata automatica);
- **certo ma con durata incerta**: rosso diretto → assenza alla giornata successiva garantita (squalifica minima 1 e comunque l'organo disciplinare decide entro pochi giorni), ma la durata oltre la prima giornata non e' ricostruibile dai soli cartellini;
- **residuo non deterministico**: ricorsi accolti (annullamento), aggravamenti/sanzioni extra per condotta — frazione minoritaria, misurabile contro i comunicati ufficiali (§2.4).

### 2.1 Un caso noto per lega (tutti dentro la finestra dell'archivio, verificati su fonti pubbliche)

| Lega | Caso | Fatto |
|---|---|---|
| Premier League | Joao Palhinha (Fulham) 2022/23 | 14 gialli in stagione (record eguagliato PL): implica squalifica alla 5a e alla 10a — caso limite ideale per testare entrambe le soglie e i cutoff (19a/32a partita) |
| Serie A | Gatti e McKennie (Juventus), febbraio 2024 | fermati dal Giudice Sportivo per somma di ammonizioni (turno 2023/24) |
| La Liga | Alejandro Catena (Osasuna), aprile 2026 | 5a gialla del ciclo → squalificato per la jornada 33 |
| Bundesliga | Michael Olise (Bayern), febbraio 2026 | 5a gialla → un turno di stop (piu' Kevin Diks, Gladbach, stesso meccanismo) |
| Ligue 1 | Pierre Lees-Melou (Brest), comunicato LFP 17/04/2024 | "un match ferme a la suite d'un troisieme avertissement dans une periode incluant 10 rencontres" — la regola pre-2025/25 applicata |

### 2.2 Reset/azzeramenti a meta' stagione: verifica esplicita per lega

Nessuna delle 5 leghe ha un azzeramento del conteggio a meta' stagione; esistono pero' due meccanismi diversi che il motore deve trattare in modo diverso:

| Lega | Reset meta' stagione? | Cosa esiste invece |
|---|---|---|
| Serie A | **No** — testo ufficiale CGS art. 19 c.9: le ammonizioni non efficaci "divengono inefficaci al termine della stagione sportiva" (o al trasferimento in Lega diversa); nessun'altra scadenza | solo la progressione dei cicli (5; poi 4, 4, 3, 2, poi ogni ammonizione — confermata dal testo FIGC ufficiale) |
| Premier League | **No** (il conteggio NON si azzera) | **scadenze delle soglie**: la soglia a 5 vale solo fino alla 19a partita di campionato della squadra, quella a 10 fino alla 32a; dopo restano raggiungibili solo le soglie superiori (10/15). Il motore deve usare l'ordine temporale delle partite, non il conteggio secco |
| La Liga | **No** — cicli dentro "la misma temporada y competicion" (art. 112.1 RFEF, testo ufficiale) | azzeramento solo tra stagioni + **esenzione ultima giornata** (art. 112.4, in vigore dal 2019/20, approvato dal CSD il 19/05/2020): se la 5a gialla arriva nell'ultima partita della competizione, la squalifica NON si applica. Tutte le stagioni del nostro perimetro sono post-riforma. Test per il motore: chi prende la 5a gialla alla giornata 38 NON deve risultare assente alla giornata 1 della stagione dopo (prima del 2019/20 sarebbe stato il contrario: caso Cheryshev 2015) |
| Bundesliga | **No** — la conta riparte da zero solo a inizio stagione successiva | nulla durante la stagione |
| Ligue 1 | **No** in entrambi i regimi | pre-2025/26: finestra mobile di 10 incontri (nessun concetto di reset); dal 2025/26: cicli a 5 con reset solo a fine stagione (dichiarato nella riforma LFP) |

**Casi noti che attraversano il punto critico (verificati, uno per lega dove il punto esiste)**:

- **Premier League** (scadenza soglia alla 19a partita di squadra): **Andreas Pereira** (Fulham) 2022/23 — The Athletic (16/01/2023) documenta che la sua 5a ammonizione arrivo' DOPO la 19a partita del Fulham e che, unico fra tutti i giocatori a 5 gialli elencati, NON sconteggio' alcuna squalifica, mentre tutti gli altri (Bentancur, Bissouma, Bruno Fernandes, Caicedo, Dalot, Maddison, McTominay, Mitrovic...) la scontarono. Test ideale per la logica delle scadenze di soglia: il motore deve prevedere "nessuna squalifica" per Pereira e squalifica per gli altri.
- **La Liga** (esenzione ultima giornata, art. 112.4): il caso che ha MOTIVATO la regola e' **Cheryshev** (Real Madrid, Copa 2015): sconteggio' una squalifica per accumulo ereditata dalla stagione precedente giocando contro il Cadice, il Real Madrid fu escluso dalla Copa. Dal 2019/20 un caso del genere in Liga non puo' piu' accadere: test per il motore e' la 5a gialla alla giornata 38 che non produce assenza alla giornata 1 successiva.
- **Serie A** (nessun reset infrastagionale, accumulo che si trascina tra stagioni): il caso Gatti/McKennie (fantamaster 2024) e' una squalifica per accumulo within-season; il punto di confine verificabile e' la 5a gialla all'ultima giornata, che in Serie A produce squalifica da scontare alla 1a giornata della stagione successiva (differenza chiave con La Liga).
- **Bundesliga** (reset solo a inizio stagione): conteggio azzerato al via di ogni campionato; caso Olise/Diks (comunio 2026) conferma la soglia a 5 within-season.
- **Ligue 1** (cambio di regime a meta' finestra): **Lees-Melou** (Brest, decisione LFP 17/04/2024) squalificato sotto il vecchio regime "3 ammonizioni in 10 incontri"; dal 2025/26 vige il flat-5. Il motore deve essere season-aware sul confine.

Fonti secondarie che parlano di "reset a meta' stagione in Serie A" risultano pagine SEO inaffidabili e sono state scartate: fa fede il testo CGS (files.figc.it) che non contiene alcun azzeramento infrastagionale; l'eventuale smentita empirica emergerebbe comunque dal confronto motore↔comunicati (§2.4) come eccesso sistematico di falsi positivi in una precisa finestra.

### 2.3 Perimetro competizione: solo campionato o cumulo con le coppe? (verifica esplicita)

| Lega | Accumulo gialli | Conseguenza per il motore basato su Understat (solo campionato) |
|---|---|---|
| Serie A | solo campionato (Coppa Italia e UEFA hanno conteggi separati; squalifiche di coppa si scontano in coppa) | corretto |
| Premier League | solo campionato dal 2018/19 (i gialli non comunicano piu' con FA Cup/Carabao Cup; i rossi si') | corretto per le soglie a gialli; i rossi in coppa non servono per prevedere assenze di campionato... tranne il caso di rosso in coppa scontato anche in campionato (regola PL sui rossi cross-competition): margine residuo da conteggiare in audit |
| La Liga | solo Liga: art. 112.1 dice "misma temporada y competicion" (5 in Liga, 3 in Copa; i cicli di Copa si azzerano dopo i quarti di finale) | corretto |
| Bundesliga | solo Bundesliga (Pokal separato, esplicitato) | corretto |
| Ligue 1 | **CUMULA con le coppe nazionali in ENTRAMBI i regimi**: pre-2025/26 le 3 ammonizioni e la finestra di 10 incontri valgono su "Ligue 1, Coupe de France, Trophée des Champions" (testo delle decisioni LFP); dal 2025/26 la regola a 5 gialli "applies across all domestic competitions, including the Coupe de France and the Trophée des Champions" (comunicato riforma) | **DICHIARATO, non silenziato: per la Ligue 1 il motore a solo campionato SOTTOSTIMA le squalifiche vicino alla soglia** — non vede i gialli di Coupe de France e sbaglia il conteggio della finestra di 10 incontri. La Ligue 1 va trattata come lega a copertura parziale finche' non si aggiungono i cartellini di coppa (fuori dal perimetro Understat) |

Nota per tutte le leghe: i cartellini delle competizioni UEFA non concorrono mai alle squalifiche di campionato (le squalifiche UEFA si scontano nelle coppe UEFA), quindi il motore di campionato non perde nulla dall'Europa.

### 2.4 Ground truth ufficiali gratuite per validare la ricostruzione (non scraping)

- Serie A: comunicati ufficiali del Giudice Sportivo (Lega Serie A / FIGC), pubblicati a ogni turno con le squalifiche "per recidivita' in ammonizione (V infr.)" esplicite;
- Premier League: elenco squalifiche/diffidati sul sito ufficiale della Premier League (aggiornato) + decisioni disciplinari FA;
- La Liga: resoluciones del Juez de Competicion (RFEF);
- Bundesliga: decisioni dello Sportgericht DFB (pubblicate);
- Ligue 1: decisioni della Commission de Discipline LFP pubblicate su lfp.fr (verificate: formato stabile almeno dal 2024).

Protocollo di verifica (da eseguire quando si rigenera l'archivio, §6): il motore deterministico genera "assente atteso" per ogni giornata; si confronta (a) contro l'archivio stesso (il giocatore NON ha righe nella partita successiva della stessa lega-stagione) e (b) contro i comunicati ufficiali sui casi campione; precisione/richiamo per lega, con i residuali contati e spiegati (ricorsi, ultima giornata, trasferimenti).

## 3. Convocazioni in nazionale: storico 2022→oggi

- **Tornei finali (gli unici con archivio stabile)**: liste ufficiali FIFA (PDF "Squad Lists" su fdp.fifa.org per Qatar 2022), Fjelstul World Cup Database (tutte le edizioni, tabella `squads` su datahub.io), openfootball/worldcup.json (pubblico dominio, 2018/2022/2026); analogo per gli Europei UEFA. Nel perimetro coprono Nov–Dic 2022, Giu–Lug 2024 (Euro), Giu–Lug 2026 (Mondiale).
- **Finestre ordinarie (Nations League, qualificazioni, amichevoli)**: **nessuna fonte pubblica stabile** con storico: le federazioni pubblicano le liste come notizie sul proprio sito (formato editoriale, niente API, pagine che cambiano struttura); nessuna delle librerie gia' in uso espone convocazioni; API-Football copre molte partite di nazionali ma con formazioni post-match, non liste convocabili pre-finestra.
- **Verdetto**: lo storico per-finestra 2022→oggi **non e' acquisibile da fonte stabile**; si puo' (a) usare i dati dei tornei finali + un flag statico "nazionale" per chi vi ha partecipato (sufficiente se l'uso e' rischio fatica/rotazione al rientro), e (b) iniziare la **raccolta passiva** dalle pagine federali da ora in poi, sapendo che e' scraping editoriale fragile. Le assenze *conseguenti* agli impegni in nazionale (infortuni in nazionale) arrivano comunque dai canali infortuni del club (§4).

## 4. Infortuni: profondita' storica reale di WhoScored via soccerdata

- **Evidenza nuova, documentale**: la guida ufficiale di soccerdata 1.9.1 mostra `read_missing_players()` funzionante sulla partita Burnley–Manchester United del **12/01/2021** (match_id 1485184), cioe' su una partita gia' giocata da ~2 anni all'epoca della docs: la tabella "missing players" **persiste nelle preview delle partite passate**, non solo in quelle future. Il nostro perimetro (dal 2022/23) e' piu' recente di cosi'.
- Campi restituiti: `player`, `player_id` (stabile), `reason`, `status` per squadra. Il campo `status` (es. `Out` vs `Doubtful`) e' esattamente il discriminatore per "manca **di certo**": solo `Out` + squalificati contano come assenza certa; i `Doubtful` vanno trattati come incerti (questo risolve anche la sovrapposizione con le squalifiche del §2: la fonte WhoScored elenca anche gli squalificati, il motore a cartellini resta la via deterministica a costo zero).
- **Campionamento REALE eseguito (non una partita sola)**: il workflow `.github/workflows/whoscored_missing_sample.yml` (stesso escamotage GitHub Actions della Parte A) ha eseguito `audit/whoscored_missing_players_sample.py` sul perimetro esatto — 5 leghe × stagioni 2223–2627, campione stratificato per cella (8 partite a quantili equispaziati), con diagnosi diretta del sito. Risultato MISURATO e refertato (artifact + commento sul PR): **WhoScored blocca in modo hard il client/IP dei runner**. Su 12/12 tentativi (home, pagina lega, preview storica 2021) il sito ha servito la pagina Cloudflare "Sorry, you have been blocked" (h1) senza alcun dato (`allRegions`, select stagioni e `missing-players` tutti assenti), sia in headless sia in headed, anche riprovando a distanza. Non e' un limite di rate o di attesa: e' un blocco a livello IP/ASN (datacenter) di Cloudflare che impedisce del tutto la lettura automatizzata da infrastruttura cloud, inclusa la sandbox di lavoro. Di conseguenza la **% di copertura campionata nel perimetro non e' stimabile da GitHub Actions**: il dato "assenze pre-match" esiste sulla fonte (le preview passate persistono, v. punto sopra) ma la via d'accesso gratuita e automatizzata usata per il PPDA/deep qui NON funziona.
- **Implicazione dichiarata, non silenziata**: le assenze per INFORTUNIO non sono acquisibili in modo automatico a costo zero dal cloud; restano acquisibili solo (i) da un client residenziale/non-bloccato (raccolta prospettica), oppure (ii) pagando una fonte che le esponga via API. Le assenze per SQUALIFICA restano invece deterministiche e a costo zero dal motore a cartellini (§2), che non dipende da WhoScored.
- Restano dichiarati e non rimossi: (a) fonte non ufficiale, ToS restrittivi; (b) per un eventuale accesso da client non-bloccato, rate limit 5–10 s e trasporto Selenium/Chrome; (c) la stima di copertura % va comunque misurata su quel client prima dell'adozione.
- Alternativa gia' in coda: per la sola Premier League l'archivio FPL (vaastav) offre `status`/`news`/`chance_of_playing_next_round` per giornata, 2016/17→2025/26, gratuito — utilizzabile come secondo parere di validazione sulla PL.

## 5. La pipeline PR #23 basta per il proxy di valore?

Campi salvati oggi per riga giocatore-partita (verificato sul codice di `update_all_ppda_player_db.py`, funzione `records_from_player_match_stats`): `season, id, date, team, opponent, venue, player_id, player, position, minutes, goals, own_goals, shots, xg, xg_chain, xg_buildup, assists, xa, key_passes, yellow_cards, red_cards` (+ flag di coerenza data/stagione). Copertura finestra: 100% delle 7276 partite, 224.902 righe (referto Parte A).

**Bastano per i proxy semplici richiesti, senza toccare la pipeline**:
- `xG/90` = Σxg / Σminutes × 90 su finestra mobile, per `player_id`;
- `(gol+assist)/90` = Σ(goals+assists) / Σminutes × 90;
- varianti: `xA/90`, `(xG+xA)/90`, tiri/90 — tutti gia' calcolabili;
- il join con l'assenza (da §2/§4) avviene su `(squadra, stagione, giocatore)` — stesso problema resolver gia' censito nel referto a costo zero, stessa soluzione in tre stadi.

**Gaps dichiarati** (dichiarazione di fattibilita', non opinione sul modello):
1. **portieri**: le righe Understat dei portieri non hanno segnale offensivo; serve un proxy diverso (es. confronto xG-concessi/squadra con e senza il portiere, calcolabile dagli archivi esistenti ma e' una scelta da validare, non un dato da acquisire);
2. **difensori/mediani puri**: nessuna statistica difensiva in Understat (niente tackle/interventi) → il proxy offensivo li sottostima sistematicamente;
3. **eta'**: non presente nelle righe (servirebbe anagrafica separata se il peso la richiedesse);
4. **minuti con recupero**: dichiarati in Parte A (campo `time` di Understat) → denominatore /90 leggermente sovrastimato, ma omogeneo tra giocatori;
5. **cold start**: nuovi acquisti senza storico nel perimetro (finestra dal 2022/23) e giocatori arrivati a stagione in corso (storico parziale); i trasferiti a meta' stagione compaiono sotto due squadre: la finestra mobile va fatta per `player_id`, non per squadra;
6. **solo campionato**: minuti di coppe non presenti (segnale rotazione europeo fuori perimetro).

## 6. Piano di verifica concreta (tutto a costo zero, prima di qualunque pagamento)

1. Rigenerare l'archivio `player_match` col workflow gia' esistente della Parte A (`ppda_player_verify.yml`) — nessuna acquisizione "nuova", e' lo stesso perimetro gia' approvato;
2. eseguire il motore deterministico squalifiche (§2) sull'archivio e misurare precisione/richiamo contro (a) l'assenza nella partita successiva e (b) i comunicati ufficiali sui 5 casi campione;
3. **campionamento reale gia' predisposto**: `audit/whoscored_missing_players_sample.py` + workflow `.github/workflows/whoscored_missing_sample.yml` (stesso escamotage GitHub Actions della Parte A per le fonti irraggiungibili dalla sandbox): campione stratificato per lega × stagione (default 8 partite a quantili equispaziati per cella, 25 celle, ~225 preview), con stati espliciti OK_ROWS / OK_EMPTY_SECTION / SECTION_MISSING / BLOCKED / FAILED e copertura % per lega, stagione e cella come artifact + log. Il push sul branch esegue il campionamento; il risultato va refertato qui prima di qualunque adozione;
4. misurare la % di join dei nomi §5 sul campione;
5. refertare i numeri PRIMA di ogni decisione su abbonamenti; le probabili formazioni restano fuori perimetro (investimento solo prospettico, rimandato a dopo la verifica del segnale con le assenze certe).

## 7. Limiti dichiarati

- Le regole del §2 sono verificate su fonti pubbliche/regolamenti citati, ma la formulazione esatta dei cicli (specie Serie A oltre il primo ciclo) va confermata sul testo normativo vigente al momento dell'implementazione;
- il caso "persistenza preview storiche" di WhoScored e' provato dalla documentazione ufficiale per il 2021, non ancora campionato nel nostro perimetro;
- nessuna promessa sull'efficacia: se i dati reggono, l'impatto sul modello si testa dopo, col protocollo Parte A (CI, test sul residuo, per lega);
- nessun componente del motore toccato; nessun nuovo dato acquisito.

## Fonti

- Regolamenti e regole: FIGC art. 19 c.9 CGS (modifica 2015: squalifica alla quinta ammonizione) — sportmediaset.it/piccolopitch; Premier League/FA (5 gialli nelle prime 19, 10 entro la 32a, 15 in stagione) — premierleague.com/news/4425344, espn.com/id=37559743, nytimes.com/athletic/3611024; RFEF Codigo Disciplinario art. 112 — as.com/2012-08-15, sport.es/7590704; Bundesliga 5/10/15 gialli e separazione competizioni — goekick.com, 90min.de, dazn.com; LFP riforma 2025/26 (da 3-in-10 a 5 gialli) — sports.yahoo.com/GFFN 2025-07-04.
- Casi campione: theanalyst.com "Most Cards in a Premier League Season" (Palhinha 14 gialli 2022/23); fantamaster.it (Gatti/McKennie, 2023/24); futbolfantasy.com (Catena 2026); magazin.comunio.de (Olise/Diks 2026); lfp.fr "Commission de discipline 17/04/2024" (Lees-Melou).
- Comunicati ufficiali (ground truth): legaseriea.it/FIGC comunicati Giudice Sportivo; premierleague.com suspensions; lfp.fr discipline (verificato il formato 2024).
- Convocazioni: FIFA Squad Lists Qatar 2022 (fdp.fifa.org PDF); Fjelstul World Cup Database (datahub.io/football/worldcup); openfootball/worldcup.json (GitHub).
- Infortuni WhoScored: soccerdata 1.9.1 docs, pagina WhoScored (esempio read_missing_players su match_id 1485184, 12/01/2021) — soccerdata.readthedocs.io; preview live 2026/27 con sezione "Missing Players" (whoscored.com/matches/1980970/preview).
- Pipeline PR #23: `update_all_ppda_player_db.py` (`records_from_player_match_stats`), PR #23 merge 2026-09-16, referto `audit/results/ppda_deep_player_feasibility.md`.
