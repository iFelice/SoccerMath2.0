# Approfondimento a costo zero: soccerdata 1.9.1 per XI ufficiali storiche e assenze pre-match (Parte B)

Approfondimento del `2026-09-20` su richiesta, **prima di qualunque abbonamento a pagamento**. Metodo: audit del **sorgente del wheel pinnato** `soccerdata==1.9.1` scaricato da PyPI (che risulta anche l'**ultima release pubblicata**: `pip index versions soccerdata` → 1.9.1), piu' ricerca documentale pubblica. **Nessuna acquisizione dati eseguita, nessun codice aggiunto al progetto.**

Limite dichiarato del metodo: questa sandbox non raggiunge i siti dati (verificato: `fbref.com`, `whoscored.com`, `espn.com`, `sofascore.com` irraggiungibili), quindi i punti che richiedono un campione "dal vivo" sono marcati **[DA CAMPIONARE]** con la ricetta minima (§9), eseguibile gratis in CI o in locale in pochi minuti.

## 1. Cosa contiene DAVVERO soccerdata 1.9.1 (con una rettifica al referto precedente)

| Fonte | Classe (trasporto) | Metodi utili | Note dal sorgente |
|---|---|---|---|
| **FBref** | `BaseSeleniumReader` — **ogni pagina passa da Chrome** (`_download_and_save` usa `self._driver.get(url)`) | `read_lineup()` | rate limit interno 7 s/richiesta; rilevazione CAPTCHA integrata |
| **ESPN** | `BaseRequestsReader` — HTTP semplice, nessun browser | `read_lineup()`, `read_matchsheet()` | API JSON non ufficiale `site.api.espn.com`, senza autenticazione; nessun rate limit imposto dalla libreria |
| **WhoScored** | `BaseSeleniumReader` — **Chrome obbligatorio** | `read_missing_players()` | rate limit 5 s + fino a 5 s di jitter; solo per assenze, NON per XI |
| **Sofascore** | `BaseRequestsReader` | `read_leagues`, `read_seasons`, `read_league_table`, `read_schedule` — **nessun metodo lineup** | rettifica: la pagina docs che indica "lineups" per Sofascore si riferisce al branch di sviluppo non rilasciato; in ogni release fino alla 1.9.1 (ultima pubblicata) i metodi sono solo 4 |
| **Understat** | HTTP semplice | nulla di pre-match | post-match soltanto (gia' in uso per pesi/etichette) |

Conseguenze operative lette dal codice:
- Le leghe sono gia' mappate per tutte e 5 nel `LEAGUE_DICT` della libreria (chiavi `ENG-Premier League`, `ESP-La Liga`, `ITA-Serie A`, `GER-Bundesliga`, `FRA-Ligue 1` con codici FBref/ESPN/WhoScored/Understat) [sorgente `_config.py`].
- La CI attuale (Parte A) gira con solo `requests`: FBref e WhoScored introdurrebbero una **dipendenza nuova** (Chrome + seleniumbase/undetected-chromedriver), ESPN no.

## 2. Via n.1 per XI storiche: `FBref.read_lineup` — cosa restituisce

Dal sorgente (`fbref.py:809-899`), per ogni partita con match report:

- **campi**: `player`, `team`, `jersey_number`, `is_starter` (il marcatore "Bench" nella pagina separa titolari da panchinari: **la panchina c'e'**), piu' `position` e `minutes_played` ottenuti con merge dalla tabella statistiche della partita;
- **assenti strutturali**: nessun ID stabile del giocatore (solo testo dell'anchor: nome, niente link/ID estratti); se una pagina non ha il marcatore "Bench" la colonna `is_starter` resta non valorizzata (caso da contare in audit);
- **costo atteso**: 1 richiesta/partita, ~7.276 partite × 7 s ≈ **14–16 ore** riprendibili (cache su disco per pagina), sotto il limite dichiarato da Sports-Reference di 10 richieste/minuto (jail fino a 1 giorno se si sfora);
- **RISCHIO STRUTTURALE SOPRAVVENUTO — verificato su fonti pubbliche**: il 20/01/2026 Stats Perform (Opta) ha risolto il contratto con Sports Reference e imposto la cancellazione dei dati Opta da FBref; FBref ha dichiarato che restano i "deep historic **basic** data" e che i dati avanzati futuri saranno su scala molto minore. Le opinioni raccolte nelle comunita' confermano la sparizione di xG e dati per-tiro; **se i box "Line-ups" (anch'essi derivati dai fogli-gara Opta) siano rimasti sulle pagine partita non risulta documentato da nessuna parte**: per questa via la disponibilita' 2022/23→2026/27 e' **[DA CAMPIONARE]** prima di qualunque piano. In piu', il merge di `position`/`minutes_played` dipende dalle tabelle statistiche, che sono proprio la parte colpita dalla rimozione: anche se i lineup restassero, quei due campi possono arrivare vuoti (il merge e' `how="left"`, non darebbe errore: silenzio).

## 3. Via n.2 per XI storiche: `ESPN.read_lineup` — cosa restituisce

Dal sorgente (`espn.py:210-338`), una chiamata JSON `/summary?event={id}` a partita:

- **campi**: `player` (displayName ESPN), `team`, `position`, `formation_place`, flag `starter`, minuti di ingresso/uscita (`sub_in`/`sub_out`, da cui si ricava chi e' partito titolare e chi e' subentrato; i convocati non entrati sono distinguibili); eventuali statistiche giocatore presenti nel payload; niente numero di maglia;
- **trasporto**: HTTP semplice senza browser e senza rate limit della libreria: ~7.300 chiamate + ~1.900 scoreboard sono rapide (ordine dei minuti-ore, non decine di ore);
- **limiti**: endpoint **non ufficiale e non documentato**, profondita' storica dei roster per le 5 leghe **[DA CAMPIONARE]** (il calendario ESPN copre stagioni vecchie, ma la presenza dei roster per singolo evento va provata su 2022/23);
- stessa libreria, stesse chiavi lega: nessun'altra dipendenza oltre `soccerdata==1.9.1` gia' pinnato.

## 4. Assenze pre-match correnti: `WhoScored.read_missing_players` — fin dove arriva davvero

Dal sorgente (`whoscored.py:482-585`):

- **campi**: `player`, `player_id` (ID stabile WhoScored), `reason`, `status` per squadra, indicizzati per lega/stagione/partita — esattamente il perimetro "assenze pre-match";
- il metodo gira sullo schedule della stagione richiesta: **sulla carta** funziona per qualsiasi stagione presente nell'archivio WhoScored (che per le 5 leghe arriva almeno al 2009/10 per i dati evento), perche' visita le pagine `/Matches/{id}/Preview`;
- **ma**: la tabella `missing-players` e' un contenuto **pre-partita**. Che resti renderizzata sulle preview delle partite gia' giocate nel 2022/23 **non e' documentato** e in questa sandbox non e' verificabile: la risposta onesta e' **[DA CAMPIONARE]** con 2-3 preview vecchie per lega. Finche' quel campione non e' fatto, questa via vale come **raccolta prospettica** (assenze correnti per le partite imminenti), non come storico certo;
- costi operativi: Chrome + rate limit 5–10 s/richiesta (~15+ ore per l'intera finestra, se lo storico reggesse) e sito con protezioni anti-bot (la libreria gestisce CAPTCHA, ma solo in modalita' non-headless puo' risolverli via GUI: in CI headless si limita a ritentare 5 volte).

## 5. Affidabilita' dei nomi (il problema resolver, gia' visto altrove)

Trovato nel sorgente: la libreria **non normalizza ne' nomi squadra ne' nomi giocatore** (`TEAMNAME_REPLACEMENTS` vuoto di default, configurabile solo da file utente); ogni fonte porta la propria anagrafica:

| Fonte XI | Nomi giocatori | Esempio discrepanza vs archivio `player_match` (Understat) |
|---|---|---|
| FBref | testo con diacritici, niente ID | `Lautaro Martínez` vs `Lautaro Martinez` |
| ESPN | `displayName` ESPN (a volte forma "L. Martínez"), niente ID estratto dal codice | variante corta non risolvibile senza alias |
| WhoScored (assenze) | nome + `player_id` stabile | serve mappa WhoScored→Understat |
| TM snapshot (fallback) | nomi Transfermarkt | altro dizionario ancora |

Squadre: `Inter` (Understat/FBref) vs `Inter Milan` (ESPN) vs `Internazionale` (WhoScored): servono alias squadra esattamente come gia' fatto per i nomi football-data.org (`team_aliases.py`/`display_names.py`).

Piano resolver in tre stadi, identico in spirito a `display_names.py`:
1. join deterministico su `(squadra, stagione, nome normalizzato)` — normalizzazione NFKD senza diacritici, minuscole, punteggiatura rimossa — da una parte e dall'altra l'archivio `player_match` (che ha gia' `player`+`player_id` Understat);
2. gli irrisolti vanno in una tabella alias manuale versionata (pattern gia' in uso nel repo);
3. soglia di accettazione dichiarata **prima** dell'adozione (proposta: ≥99% delle righe risolvibile senza ambiguita' per lega, residuo contato e riportato, mai imputato a zero). La % reale e' **[DA MISURARE]** sul campione: non la promettiamo.

## 6. Copertura % attesa: dichiarazione onesta

Senza campionamento live (impossibile da questa sandbox) **non e' serio scrivere una % di copertura**: le tre incognite sono (a) esistenza dei box lineup su FBref dopo il gennaio 2026, (b) profondita' dei roster ESPN per evento, (c) persistenza della tabella assenti nelle preview WhoScored storiche. Il §9 definisce il campione minimo che trasforma queste tre incognite in numeri, al costo di ~20-30 richieste totali.

## 7. Verdetto a costo zero (provvisorio finche' il §9 non gira)

- **XI ufficiali storiche 2022/23→2025/26**: via a costo zero **plausibile e da testare per prima**. Ordine di preferenza letto dai vincoli sopra: **1) ESPN** (HTTP semplice, nessuna dipendenza nuova, veloce — se i roster storici ci sono), **2) FBref** (solo se il campione post-gennaio-2026 conferma i box lineup), **3) fallback one-shot**: lo snapshot pubblico derivato da Transfermarkt (`game_lineups`, CC0, fermo al 2026-07-06, finestra coperta per intero — con la stessa zona grigia di diritti gia' segnalata nel referto principale).
- **Assenze pre-match storiche**: finche' il campione non prova il contrario, la via WhoScored vale **solo come raccolta prospettica** (stessa conclusione del referto principale per le probabili).
- **Formazioni probabili**: il costo zero non cambia la conclusione — non esistono archivi da nessuna fonte, gratuita o a pagamento.
- Se il campione §9 boccia sia ESPN sia FBref sullo storico, allora (e solo allora) ha senso il trial gratuito di 14 giorni dei fornitori a pagamento **limitato alle XI ufficiali retroattive**, come da consegna; le probabili restano investimento a validazione solo prospettica, da rimandare a dopo aver verificato se il segnale esiste con l'XI ufficiale.

## 8. Campionamento minimo da eseguire (tutto gratuito, ~20-30 richieste)

Da eseguire in un ambiente con rete (la CI GitHub del progetto, dove Parte A gia' gira, o locale). Ogni punto e' indipendente; se un punto fallisce si passa al successivo.

1. **ESPN, profondita' roster**: per ciascuna delle 5 leghe, una partita a meta' stagione 2022/23 e una 2024/25:
   `sd.ESPN(["ENG-Premier League",...], ["2022","2024"])` → `read_schedule()` → `read_lineup(match_id=...)`.
   Criterio: presenti sia i 22 titolari sia giocatori con `sub_in`/`sub_out`;
2. **FBref, box lineup post-gennaio-2026**: una partita 2022/23 e una della stagione corrente per lega:
   `sd.FBref(...).read_lineup(match_id=...)`.
   Criterio: righe con `is_starter` valorizzato, panchina presente; registrare se `position`/`minutes_played` arrivano vuoti (effetto rimozione Opta);
3. **WhoScored, preview storiche**: per una lega, una preview di una partita 2022/23 e una 2023/24 gia' giocate + una imminente:
   `sd.WhoScored("ITA-Serie A", ["2022","2023","2025"]).read_missing_players(match_id=...)`.
   Criterio: tabella assenti non vuota sulle partite gia' giocate → storico ricostruibile; vuota → solo prospettico;
4. **Resolver**: sul campione del punto 1 (o 2), join contro `SoccerMath/database/player_match_<lega>.json` con normalizzazione §5 e contare: % risolti al primo stadio, % con alias, % irrisolvibili;
5. **Registro**: esito di ciascun punto (conteggi, % , campi vuoti) va scritto in un referto prima di decidere qualunque abbonamento — stesse regole di audit della Parte A.

## 9. Limiti dichiarati

- Audit condotto sul sorgente del wheel 1.9.1 (ultima release PyPI al 2026-09-20) e su fonti pubbliche; nessun endpoint dati e' stato chiamato;
- la raggiungibilita' futura degli endpoint non ufficiali ESPN e delle pagine WhoScored/FBref non e' garantita da nessuno: il campionamento va rifatto al momento dell'uso, e ogni tanto durante la stagione;
- la rimozione Opta da FBref (gennaio 2026) rende FBref una fonte a **rischio di disponibilita'**, indipendentemente dal suo status legale;
- WhoScored/FBref/Sofascore restano scraping di siti con ToS restrittivi: l'uso e' a rischio e onere di chi lo dispone, come gia' dichiarato nel referto principale; ESPN espone un JSON non ufficiale senza autenticazione (zona grigia analoga, ma senza ToS di scraping esplicito citato contro);
- nessuna soglia, formula o peso del motore e' stata toccata; nessun file dati aggiunto.

## Fonti

- Wheel `soccerdata-1.9.1-py3-none-any.whl` (PyPI, ultima release al 2026-09-20): `fbref.py` (`class FBref(BaseSeleniumReader)`, `read_lineup` righe 809-899, `rate_limit=7`), `espn.py` (`class ESPN(BaseRequestsReader)`, `read_lineup` righe 210-338), `whoscored.py` (`class WhoScored(BaseSeleniumReader)`, `read_missing_players` righe 482-585, `rate_limit=5`), `sofascore.py` (4 soli metodi `read_*`, nessun lineup), `_config.py` (`LEAGUE_DICT`, `TEAMNAME_REPLACEMENTS` vuoto di default), `_common.py` (`BaseSeleniumReader._download_and_save` via driver, gestione CAPTCHA).
- Sports-Reference, politica bot/traffic (FBref: max 10 richieste/minuto, jail fino a un giorno) — https://www.sports-reference.com/bot-traffic.html
- Annuncio FBref/Sports Reference sulla risoluzione del contratto Opta e The Athletic, 20-28/01/2026 (rimozione dati Opta; restano i dati storici di base) — https://www.reddit.com/r/MLS/comments/1qiku6o/fbref_stathead_data_update_losing_advanced_soccer/ , https://www.nytimes.com/athletic/7002196/2026/01/28/fbref-opta-football-data-soccer-analytics/
- Guida 2026 alle fonti (FBref utile ormai solo come storico) — https://www.liamhenshaw.com/writing/where-to-find-football-data
- soccerdata docs (FBref `read_lineup`; esempio output lineup; WhoScored `read_missing_players`) — https://soccerdata.readthedocs.io/en/latest/datasources/FBref.html , https://soccerdata.readthedocs.io/en/latest/reference/whoscored.html
- Snapshot lineup derivato da Transfermarkt (fallback one-shot) — https://github.com/dcaribou/transfermarkt-datasets
- Referto principale Parte B — `audit/results/assenze_formazioni_probabili_feasibility.md`
