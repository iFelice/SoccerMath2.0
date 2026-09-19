# Fattibilita' acquisizione: assenze pesate + formazioni probabili — PARTE B, sola ricerca

Referto di **sola ricerca di fattibilita'**: redatto manualmente il `2026-09-19` (ricerca documentale su documentazione pubblica dei fornitori e fonti terze), senza eseguire acquisizioni di dati e senza scrivere codice.

Nessuna modifica a `SoccerMath/app.py`, `SoccerMath/config.py`, `SoccerMath/models/`, a formule, soglie o pesi: **nulla di quanto descritto qui e' collegato al motore Poisson/Elo**, ne' lo diventa con questo intervento. Nessuna promessa di risultato: il referto risponde solo alla domanda "e' fattibile acquisire questi dati", non "funzioneranno". L'eventuale efficacia si testa dopo, con lo stesso rigore usato per PPDA/deep (CI, test sul residuo, per lega).

Perimetro richiesto: le 5 leghe del progetto (Serie A, Premier League, La Liga, Bundesliga, Ligue 1), finestra storica di walk-forward pari all'archivio xG esistente (stagioni 2022/23, 2023/24, 2024/25, 2025/26, piu' 2026/27 corrente = 7276 partite concluse censite in Parte A [28]).

> **Aggiornamento 2026-09-20**: approfondimento a costo zero su `soccerdata==1.9.1` (XI storiche via ESPN/FBref, assenze via WhoScored) in `audit/results/assenze_formazioni_soccerdata_zero_cost_verification.md`, inclusa la rettifica su Sofascore (nessun lettore lineup nella 1.9.1) e il rischio sopravvenuto su FBref (rimozione dati Opta, gennaio 2026). La via a costo zero va testata prima di qualunque abbonamento.

## 1. Sintesi del verdetto

| Dato | Serve per | Esiste una fonte? | Tempestivita' | Copertura storica 2022/23–2025/26 | Verdetto acquisizione |
|---|---|---|---|---|---|
| Formazioni **ufficiali** (XI + panchina) | validare il collettore, etichette reali | Si', piu' fonti | ~1h prima del kickoff | **Si'** (piu' percorsi, §4) | Fattibile |
| Formazioni **probabili** pre-match | feature predittiva | Solo Sportmonks (algo incluso / premium curato); Transfermarkt e stampa (scraping) | ore–giorni prima | **No: nessun archivio storico esiste** (§5) | Fattibile **solo prospettico** (raccolta passiva da ora) |
| Assenze: infortuni + squalifiche, con motivazione e rientro | feature "assenze pesate" | Si', piu' fonti | aggiornamenti ogni ~4h | **Parziale e disomogenea** (§6): PL completa via FPL; altre leghe da verificare in trial; istantanee statiche derivate da Transfermarkt | Fattibile prospettico; storico ricostruibile solo in parte |
| Pesi dei giocatori (minuti, contributo) | la meta' "pesate" della feature | Gia' in casa: `player_match` Understat 2022→oggi | post-match | **Si', 100%** (Parte A) | Gia' acquisito |

Le due conclusioni nette richieste dalla consegna:

1. **Sulle formazioni probabili la copertura storica e' assente, ovunque.** Nessuna fonte archivia le probabili come erano *prima* del kickoff: Sportmonks dichiara esplicitamente che la probabile viene **sostituita** dall'ufficiale appena confermata [9], Transfermarkt e la stampa non espongono archivi API. Quindi: buono **solo per raccolta passiva da ora in poi**, non per backtest sulle stagioni passate. Storicamente si puo' validare solo un eventuale predittore *nostro* dell'XI, addestrato su XI ufficiali + assenze datate.
2. **Sulle assenze lo storico e' parziale**: completo e gratuito solo per la Premier League (archivio FPL 2016/17→2025/26 [22][23]); per le altre quattro leghe la profondita' delle fonti a pagamento **non e' documentata** e va misurata nei periodi di prova (§8). Dire chiaramente questo e' il punto: un walk-forward sulle assenze per tutte e 5 le leghe dal 2022/23 potrebbe non essere ricostruibile con fedelta' point-in-time.

## 2. Cosa espongono le API gia' in uso (verificato su documentazione)

- **football-data.org v4** (in uso, piano Free): il piano Free **non include alcun dato giocatore**: niente formazioni, sostituzioni o cartellini; questi richiedono l'add-on a pagamento "Deep Data" (≈29 €/mese sul piano base, incluso dal piano Standard in su) esposti via header `X-Unfold-Lineups` e simili [2][3][4][27]. Anche pagando: **solo formazioni ufficiali**, e in v4 **non esiste alcun endpoint infortuni/squalifiche** ne' un prodotto "probabili formazioni". Sul perimetro attuale del progetto (piano Free) football-data.org non puo' contribuire a Parte B.
- **The Odds API** (in uso): solo quote; nulla di pertinente.
- **Understat via `soccerdata==1.9.1`** (in uso): strettamente post-match, quindi non fornisce alcuna informazione pre-partita. Pero' l'archivio `player_match` gia' acquisito (minuti, cartellini per giocatore-partita, 4 stagioni complete, Parte A) e' il **materiale per i pesi** e per le etichette oggettive di assenza ("il giocatore non ha giocato"), utili a validare a posteriori qualsiasi fonte di assenze. Nessun nuovo acquisto necessario per questa meta'.

## 3. Fonti candidate non in uso (quadro generale)

- **API-Football (API-Sports)**: `/fixtures/lineups` pubblica l'XI ufficiale tipicamente **30–60 minuti prima** del kickoff (guida ufficiale: iniziare il polling a -90'); `/injuries` aggiornato **ogni 4 ore**, queryable per lega+stagione, partita, squadra o data, con tipo `Injury|Suspension` e motivazione; `/sidelined` da' lo storico datato per giocatore. Piani: Free 100 richieste/giorno su tutti gli endpoint ("stagioni recenti"), Pro 19 $/mese (7.500 richieste/giorno), Ultra 29 $/mese, Mega 39 $/mese [5][6]. La copertura (flag `coverage.lineups`, `coverage.injuries`) va letta per ogni coppia lega-stagione prima di pianificare l'acquisizione [5].
- **Sportmonks Football API v3**: formazioni ufficiali ~1h prima incluse in **tutti** i piani; `predictedLineups` (probabili algoritmiche da storico + infortuni/squalifiche) incluse nei piani correnti; **Premium Expected Lineups** (curate da analisti umani su notizie, conferenze stampa, bollettini) come add-on a pagamento; assenze via include `sidelined` (correnti) e `sidelinedHistory` (storico, con partite saltate) inclusi in tutti i piani [8][9][10][12]. Piani: Starter 29 €/mese (5 leghe), Growth 99 €/mese (30), Pro 249 €/mese; prova gratuita 14 giorni su piani a pagamento; il piano gratuito copre solo Superliga danese e Scottish Premiership [11][13].
- **Transfermarkt**: ha le "probabili" editoriali sulla pagina partita (di norma nelle ore/giorni precedenti il kickoff, senza SLA), ma i **Termini d'Uso vietano esplicitamente** l'accesso automatizzato ("not permitted to access or copy the Digital Content using bots, spiders, screen scraping or other automated processes") [15]. Segnale di fragilita' dell'ecosistema di scraping su TM: la piu' grande pipeline pubblica derivata (dcaribou/transfermarkt-datasets) **ha sospeso gli aggiornamenti a meta' luglio 2026** [16]. Nota di coerenza col progetto: i valori di mercato usati in Parte A sono rilevazioni **manuali** point-in-time (CSV), approccio compatibile con i ToS; una raccolta manuale analoga delle probabili su ~10 partite/giorno non e' pero' un'opzione realistica continuativa.
- **soccerdata 1.9.1** (gia' pinnata nel progetto): espone lettori di formazioni **ufficiali** storiche — `FBref.read_lineup` e `ESPN.read_lineup` — e, via WhoScored, `read_missing_players()`: "lista di giocatori infortunati e squalificati prima di ogni partita" [17][18]. Rettifica del 2026-09-20 (vedi approfondimento a costo zero): nella release pinnata **Sofascore non ha alcun lettore lineup** (la docs che li cita si riferisce al branch di sviluppo mai rilasciato); FBref e WhoScored richiedono Chrome headless (sono `BaseSeleniumReader`); la disponibilita' effettiva 2022/23→2026/27 e' da campionare, anche perche' FBref ha perso i dati Opta nel gennaio 2026. WhoScored resta l'unico canale **pre-match sulle assenze** dentro la libreria gia' in uso, ma la profondita' storica delle preview e' non documentata: da trattare come raccolta prospettica finche' un campione non dice il contrario.
- **FBref** (dati Opta): formazioni ufficiali delle top-5 dall'era Opta (da ~2017/18, comunque ben prima del 2022/23; da campionare per lega) e cartellini/minuti per giocatore (base per ricostruire le **squalifiche** dalle regole di accumulo, §6). Limite duro dichiarato: **10 richieste/minuto**, sessione in "jail" fino a un giorno se si sfora [19].
- **StatsBomb Open Data**: gratuito, con formazioni ed eventi infortunio, ma copre solo alcune competizioni/stagioni selezionate (non le 5 leghe per 4 stagioni consecutive): non e' una fonte sistematica per questo perimetro.
- **Fonti editoriali** (Gazzetta/Fantanews per la Serie A, ecc.): probabili e liste assenti per giornata [26]; senza archivio, senza API, scraping fragile: solo complemento eventuale.

## 4. Formazioni ufficiali: copertura storica e percorso di backfill

Per il walk-forward servono le XI reali delle 7276 partite dell'archivio xG. Opzioni, tutte praticabili:

| Percorso | Costo | Note |
|---|---|---|
| dcaribou/transfermarkt-datasets (snapshot) | 0 (CC0) | Tabella `game_lineups` (titolari + panchina, ~3,17 mln righe), snapshot fermo al **2026-07-06** che copre l'intera finestra 2022/23–2025/26; aggiornamenti **sospesi** e dati derivati da scraping TM (zona grigia sui diritti): va bene come backfill one-shot, non come pipeline continua [16] |
| FBref via `soccerdata.FBref.read_lineup` | 0 (rate-limited) | ~7.300 partite ≈ 12–24 h di crawl al limite di 10 req/min, riprendibile; fonte ufficiale Opta; da campionare prima la disponibilita' 2022/23 per lega [17][19] |
| API-Football Pro (1 mese) | 19 $ | `/fixtures/lineups` per fixture; ~7.300 chiamate < 7.500 richieste/giorno del piano Pro: backfill in ~1 giorno; prima verificare i flag `coverage.lineups` 2022–2025 [5][6] |
| Sportmonks | da 29 €/mese + add-on | Piano base: ultime **3 stagioni**; lo storico piu' vecchio e' un add-on una tantum [13] |
| football-data.org Deep Data | da 29 €/mese | Solo se interessa anche in produzione; profondita' storica delle formazioni da verificare col manutentore [2][3] |

Limite strutturale da ricordare: l'XI ufficiale esiste solo a ~1h dal kickoff. Il flusso attuale dell'app legge le partite in stato `TIMED/SCHEDULED` (tipicamente ≥24h prima): le ufficiali, da sole, **non** sono una feature pre-match al momento in cui oggi girano le previsioni; servono come etichette e come validazione del collettore di probabili, oppure richiedono un secondo passaggio a T-1h.

## 5. Formazioni probabili: perche' lo storico non esiste (dirlo chiaramente)

- Sportmonks, l'unica fonte API con probabili strutturate, dichiara che la probabile "viene sostituita dalla formazione ufficiale una volta confermata" (`lineup_confirmed`): l'oggetto pre-match **non viene archiviato** [8][9].
- Transfermarkt e le fonti editoriali non espongono archivi storici consultabili via API; lo scraping viola i ToS [15] e l'ecosistema pubblico si e' appena fermato [16].
- Conseguenza: **nessun backtest sulle probabili "come erano all'epoca" e' possibile** per il 2022/23–2025/26. Le uniche due strade storiche sono: (a) validare un predittore interno dell'XI costruito su ufficiali+assenze storiche; (b) iniziare ora la **raccolta passiva** (snapshot datati delle probabili per ogni partita) cosi' che il walk-forward esista dal 2026/27 in poi.

Opzioni prospettiche per le probabili (dal 2026/27), con i numeri dichiarati dai fornitori:

| Opzione | Costo | Natura | Accuratezza dichiarata (top-5) |
|---|---|---|---|
| Sportmonks `predictedLineups` | incluso da Starter (29 €/mese) | algoritmica (storico XI + assenze), nessun SLA | non dichiarata |
| Sportmonks Premium Expected Lineups | **159–199 €/mese** di add-on su Growth+ | curata da analisti (notizie, conferenze, bollettini) [9][14] | dichiarata: Bundesliga 87%, Serie A 87%, PL 84%, La Liga 75% [7] |
| Scraping Transfermarkt / stampa | ~0 | violazione ToS / fragile | n/d — **non raccomandato** |

## 6. Assenze (infortuni + squalifiche): copertura storica per lega

| Via | Finestra disponibile | Note |
|---|---|---|
| **FPL (Premier League soltanto)** | **2016/17 → 2025/26 completa**, granularita' per giornata (stato, probabilita' di giocare, nota testuale, rientro atteso) | L'API live ufficiale svuota lo storico a fine stagione [22], ma l'archivio comunitario vaastav copre l'intera finestra [23]. Unico storico **completo e gratuito**, ma solo PL [21] |
| Sportmonks `sidelinedHistory` | incluse in tutti i piani le ultime **3 stagioni**; il piu' vecchio e' add-on una tantum; profondita' "varia per lega" [13][12] | Record con tipo, date inizio/fine, **partite saltate**: sufficiente a costruire assenze pesate; profondita' 2022/23 da **misurare in trial** |
| API-Football `/sidelined` | non documentata | Storico datato per giocatore (tipo + date); profondita' 2022–2026 da **misurare** con la chiave free su un campione di giocatori con assenze note [5] |
| Snapshot "Injuries from Transfermarkt" (figshare) | ~107.000 infortuni, ~18.500 giocatori, congelato (~2023/24) | Derivato da scraping TM (stessi problemi di licenza); copre solo parte della finestra [24]; la comunita' indica "scraping TM o pagare Opta" come uniche vie per lo storico infortuni [25] |
| Ricostruzione squalifiche da cartellini | **2022/23–2025/26 completa** (cartellini gia' in `player_match` Understat, o da FBref) | Servono le regole di accumulo per lega/stagione (soglie, azzeramenti): ricostruzione deterministica ma con costo di codifica per lega |
| WhoScored `read_missing_players` | solo partite correnti/imminenti | In libreria soccerdata gia' pinnata [18]; fonte non ufficiale, nessun archivio: solo eventuale raccolta passiva |

Sintesi onesta: **per le assenze pre-match point-in-time la ricostruzione storica e' garantita solo per la Premier League**; per le altre quattro leghe dipende da quanto sono profondi gli archivi Sportmonks/API-Football (non documentato: da misurare, §8) o accetta la zona grigia degli snapshot derivati da Transfermarkt. Se la verifica in trial desse profondita' insufficiente, la scelta razionale resta la stessa delle probabili: **raccolta passiva da ora, backtest solo su quanto ricostruibile**.

## 7. Costi minimi realistici (senza promettere nulla sull'efficacia)

| Scenario | Costo | Cosa si ottiene |
|---|---|---|
| Minimo prospettico (raccolta passiva 2026/27) | Sportmonks Starter **29 €/mese** oppure API-Football Pro **19 $/mese** | ufficiali + assenze correnti (+ probabili algoritmiche con Sportmonks); nessun dato storico |
| Storico formazioni ufficiali (backfill una tantum) | 0 (snapshot TM / FBref rate-limited) oppure 1 mese di API-Football Pro (19 $) | XI reali 2022/23–2025/26 per validazioni/etichette |
| Storico assenze | 0 per la PL (vaastav/FPL); trial Sportmonks/API-Football per le altre (§8) | assenze datate dove la profondita' lo consente |
| Probabili "vere" (curate) in produzione | Sportmonks Growth + add-on Expected Lineups ≈ **258–298 €/mese** | probabili pre-match human-curated; nessun archivio storico |

## 8. Checklist di verifica prima di qualunque implementazione (tutta eseguibile gratis o in trial)

> Ordine aggiornato 2026-09-20: prima i punti a **costo zero** (campionamento soccerdata 1.9.1: ESPN/FBref/WhoScored + resolver nomi), definiti in `audit/results/assenze_formazioni_soccerdata_zero_cost_verification.md` §8; i punti 1–2 a pagamento (API-Football/Sportmonks) solo se il campionamento a costo zero boccia lo storico delle XI ufficiali, e comunque mai per le probabili.

1. **API-Football (chiave free, 100 richieste/giorno)**: per le 5 leghe × stagioni 2022–2026 leggere `coverage.lineups` e `coverage.injuries` da `/leagues`; contare i record di `/injuries?league&season=2023`; su ~10 giocatori con assenze note nel 2022/23 verificare che `/sidelined` restituisca l'evento datato.
2. **Sportmonks (trial 14 giorni, piano Growth)**: su 2 squadre per lega, contare i record di `sidelinedHistory` per stagione (misura la profondita' reale); su una partita imminente verificare presenza e orario di pubblicazione di `predictedLineups`, e **se** la probabile resta leggibile dopo la conferma dell'ufficiale (atteso: no [9]).
3. **FBref via soccerdata 1.9.1**: campionare 1 partita 2022/23 per lega con `FBref.read_lineup`; misurare il costo del crawl completo al limite dichiarato di 10 richieste/minuto [19].
4. **FPL/vaastav**: nei `merged_gw.csv` 2022-23→2025-26 verificare presenza di `status`, `news`, `chance_of_playing_next_round` [23].
5. **football-data.org**: se si volesse riusare il fornitore attuale, chiedere al manutentore da quale stagione il Deep Data espone le formazioni storiche (documentazione non consultabile su questo punto).

Solo se i punti 1–4 confermano le profondita' necessarie ha senso passare a un'eventuale Parte B di implementazione; l'efficacia predittiva resterebbe comunque da dimostrare **dopo**, con il protocollo Parte A (CI, test sul residuo, per lega).

## 9. Limiti dichiarati di questo referto

- E' una ricerca documentale del 2026-09-19 su documentazione pubblica e fonti terze: prezzi e piani possono cambiare; fa fede il fornitore al momento dell'eventuale acquisto.
- Le profondita' storiche **non documentate** (API-Football `/sidelined`, Sportmonks `sidelinedHistory`, formazioni storiche del Deep Data di football-data.org) sono indicate come tali e non come fatti: la checklist §8 esiste per misurarle.
- Le accuratezze delle probabili Sportmonks (87%/87%/84%/75%) sono **dichiarazioni del fornitore** [7], non verificate da noi, e non costituiscono in alcun modo una promessa di risultato.
- I dati derivati da scraping Transfermarkt (snapshot lineup, dataset infortuni figshare) pongono problemi di diritti: il referto li segnala come esistenti ma **non ne raccomanda** l'uso senza valutazione; i ToS di Transfermarkt vietano la raccolta automatizzata [15].
- Nessuna acquisizione e' stata eseguita; nessun file dati aggiunto; nessun componente del motore toccato.

## Fonti consultate (accesso 2026-09-19)

- [1] football-data.org, homepage (scopo del servizio: "squads, lineups/subs") — https://www.football-data.org/
- [2] getbruin.com, "football-data.org Source Research" (tier map, Deep Data 29 €, header X-Unfold-*) — https://getbruin.com/docs/ingestr/soccer-sources/football-data-org.html
- [3] TheStatsAPI, confronto con football-data.org (player data solo con add-on Deep Data) — https://www.thestatsapi.com/blog/thestatsapi-vs-football-data-org
- [4] Highlightly, "Best Football APIs in 2026" (Deep Data 29 €/mese) — https://highlightly.net/blogs/best-football-apis-in-2026
- [5] API-Football, "Complete beginner's guide" (lineups a -30/60', /injuries ogni 4h, /sidelined, coverage flags, piani) — https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide
- [6] api.market, "10 Best Sports APIs" (piani API-Football: Pro 19 $/7.500 richieste/giorno) — https://api.market/blog/recodex/allsportsapi/best-sports-api
- [7] Sportmonks, blog "Premium Expected Lineups" (accuratezze dichiarate per lega) — https://www.sportmonks.com/blogs/premium-expected-lineups/
- [8] Sportmonks docs, "Predicted Lineups" (algoritmiche in tutti i piani; sostituite dall'ufficiale) — https://docs.sportmonks.com/v3/tutorials-and-guides/tutorials/includes/predicted-lineups
- [9] Sportmonks docs, "Premium Expected Lineups" (add-on 199 €/mese su Growth+; curate da umani) — https://docs.sportmonks.com/v3/endpoints-and-entities/endpoints/premium-expected-lineups
- [10] Sportmonks docs, "Lineups and formations" (ufficiali ~1h prima, in tutti i piani) — https://docs.sportmonks.com/v3/tutorials-and-guides/tutorials/lineups-and-formations
- [11] Sportmonks docs, Changelog 2026-03-09 (piani Starter 29 € / Growth 99 € / Pro 249 €) — https://docs.sportmonks.com/v3/changelog/changelog
- [12] Sportmonks, "Injuries and Suspensions" (sidelined/sidelinedHistory, partite saltate) — https://www.sportmonks.com/glossary/injuries-and-suspensions/
- [13] Sportmonks FAQ (storico >3 stagioni = add-on una tantum; free = solo Superliga DK + Scottish Premiership; trial 14 giorni) — https://www.sportmonks.com/faq/
- [14] Sportmonks, "Expected Lineups API" (159 €/mese annuale o 199 € mensile su Growth/Pro) — https://www.sportmonks.com/football-api/expected-lineups-api/
- [15] Transfermarkt, Terms of Use §11.1 (divieto di scraping) — https://www.transfermarkt.co.uk/intern/anb
- [16] dcaribou/transfermarkt-datasets + Kaggle "player-scores" (game_lineups; snapshot al 2026-07-06; aggiornamenti in pausa da meta' luglio 2026) — https://github.com/dcaribou/transfermarkt-datasets , https://www.kaggle.com/datasets/davidcariboo/player-scores
- [17] soccerdata 1.9.1 docs, "Overview of Data Sources" (FBref/ESPN/Sofascore lineups; WhoScored preview) — https://soccerdata.readthedocs.io/en/latest/datasources/
- [18] soccerdata docs, WhoScored.read_missing_players — https://soccerdata.readthedocs.io/en/latest/reference/whoscored.html
- [19] Sports-Reference, "Bot/Scraping/Crawler Traffic" (FBref: max 10 richieste/minuto) — https://www.sports-reference.com/bot-traffic.html
- [20] worldfootballR, "Extracting data from FBref" (match lineups) — https://jaseziv.github.io/worldfootballR/articles/extract-fbref-data.html
- [21] Apify, "Premier League Injury List" (feed FPL ufficiale: campi e assenza di backfill; solo PL) — https://apify.com/gganbukim/premier-league-injury-scraper
- [22] lucifer0096/FPL-Analytics (l'API live FPL svuota lo storico a fine stagione) — https://github.com/lucifer0096/FPL-Analytics
- [23] vaastav/Fantasy-Premier-League (merged_gw.csv per stagione 2016/17+) — https://github.com/vaastav/Fantasy-Premier-League
- [24] figshare, "Injuries from Transfermarkt.com" (~107k infortuni, snapshot) — https://figshare.com/articles/dataset/Injuries_from_Transfermarkt_com/25648788/2
- [25] Reddit r/webdev, "Soccer Injury History API?" (scraping TM o Opta come uniche vie indicate) — https://www.reddit.com/r/webdev/comments/1cigjk6/soccer_injury_history_api/
- [26] Gazzetta, "Serie A Absentees" esempio di fonte editoriale per giornata — https://gazzetta.it/en/football/fantanews/tools-fantasy-football/unavailable-players/18-09-2026/serie-absentees-injured-and-suspended-for-matchday-5.shtml
- [27] GitHub issue nimeshjm/fantasy-football#51 (football-data.org free senza eventi/lineups; Deep Data a pagamento) — https://github.com/nimeshjm/fantasy-football/issues/51
- [28] Parte A: `audit/results/ppda_deep_player_feasibility.md` (perimetro 7276 partite, 5 leghe, stagioni 2022–2026) — file in questo repository
