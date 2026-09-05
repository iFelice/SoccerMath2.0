# Consolidamento della pipeline xG — verifica, progetto, limiti

Documento di accompagnamento all'intervento "una sola acquisizione Understat,
una sola normalizzazione dei nomi, medie stagionali derivate dall'archivio per
partita".

Non sono state toccate le formule predittive, `PRIOR_MATCHES = 6`, i pesi
Poisson/Elo, la versione del modello, né JSONBin.

---

## 1. Verifica iniziale (stato del codice prima dell'intervento)

### 1.1 Due acquisizioni Understat indipendenti

| Script | Cosa faceva | Output |
|---|---|---|
| `update_all_xg_db.py` | `soccerdata.Understat.read_schedule()` per 5 leghe × 5 stagioni | `database/xG archivio <lega>.json` (per-partita) |
| `SoccerMath/update_xg.py` | scraping HTML diretto di `understat.com/league/<id>/<season>`, parsing di `teamsData` (base64 + escape decode) | `database/xg_<lega>.json` (medie stagionali) |

Due download distinti, in due momenti distinti, con due tabelle di nomi
distinte: le medie non erano ricostruibili dall'archivio e viceversa.

Il secondo scraping era inoltre schedulato **due volte**: nel workflow
`update_xg.yml` (mar/ven 06:00) e come step `Update xG` dentro
`update_database.yml` (cron ogni 6 ore, `continue-on-error: true`).

### 1.2 Tre tabelle di normalizzazione dei nomi

* `SoccerMath/update_xg.py` → `NAME_MAP` (≈110 voci), con **4 chiavi duplicate
  nel literal** che si ombreggiavano in silenzio: `Atletico Madrid`,
  `Celta Vigo`, `Rayo Vallecano`, `Real Sociedad` (la prima occorrenza mappava
  su sé stessa, la seconda sul nome CSV corretto — vinceva la seconda, ma solo
  per l'ordine di scrittura);
* `SoccerMath/config.py` → `TEAM_NAME_MAP` + `clean_name`;
* `audit/xg_rolling_walkforward.py` → `NAME_TRANSLATE` (terza copia parziale).

Errori di mapping verificati sui dati (non ipotesi):

| Voce | Valore precedente | Valore corretto | Perché |
|---|---|---|---|
| `Athletic Bilbao` (NAME_MAP) | `Athletic Club` | `Ath Bilbao` | i CSV usano `Ath Bilbao`; `Athletic Club` non esiste come chiave dell'engine |
| `FC St. Pauli` / `St. Pauli` | `St. Pauli` | `St Pauli` | i CSV Bundesliga 2024/25 scrivono `St Pauli`, senza punto |
| `AS Saint-Étienne` | `Saint-Etienne` | `St Etienne` | il CSV Ligue 1 2024/25 scrive `St Etienne` |
| `Eintracht Frankfurt` (TEAM_NAME_MAP) | `Frankfurt` | `Ein Frankfurt` | `clean_name` è a passata singola: `Frankfurt → Ein Frankfurt` non veniva riapplicato |
| `Borussia Mönchengladbach` (TEAM_NAME_MAP) | `Monchengladbach` | `M'gladbach` | nome canonico dei CSV e chiave dell'engine |
| assenti | — | `Real Valladolid → Valladolid`, `Real Oviedo → Oviedo`, `Hertha Berlin → Hertha`, `Clermont Foot → Clermont` | titoli presenti negli archivi, mai mappati |

### 1.3 Le medie pubblicate non erano derivabili dall'archivio

`database/xg_<lega>.json` conteneva (verifica su `origin/main`):

* **27 squadre in Serie A**, 27 in Premier, **32 in La Liga**, 25 in
  Bundesliga, 23 in Ligue 1 — cioè un miscuglio di stagioni diverse
  (`Sampdoria`, `Spezia`, `Salernitana`, `Frosinone`, `Girona`, `Bochum`…);
* **coppie di alias con valori diversi** per la stessa squadra:
  `Alaves`/`Alavés`, `Espanol`/`Espanyol`, `Barcelona`/`Barça`,
  `Ath Bilbao`/`Athletic`, `Ath Madrid`/`Atleti`, `Brighton`/`Brighton Hove`,
  `Leeds`/`Leeds United`, `Wolves`/`Wolverhampton`, `Koln`/`Köln`,
  `Hamburg`/`HSV`, `St Pauli`/`St. Pauli`, `Lyon`/`Olympique Lyon`,
  `Rennes`/`Stade Rennais`, `Vallecano`/`Rayo Vallecano`, `Oviedo`/`Real
  Oviedo`, `Sociedad`/`Real Sociedad`, `Nott'm Forest`/`Nottingham`;
* **nessun campo `matches`** su nessuna squadra, quindi `get_league_engine`
  non poteva applicare lo shrinkage sul ramo xG e uno `xG_avg = 0` non era
  distinguibile da un dato rotto;
* valori non riconducibili né alla stagione corrente né a una media
  multi-stagione dell'archivio (es. Serie A `Inter` 1.826 contro 2.755
  derivato dalla stagione 2026 e 2.124 dalla media 2022-2026); alcune voci
  coincidono invece con i rapporti gol dei CSV (es. `Pisa` 0.684/1.868 =
  gol fatti/subiti per partita in `SerieA_2025.csv`).

**Conclusione:** i due file non erano equivalenti e non lo sarebbero diventati
con nessuna riscrittura "a parità di numeri". La sostituzione è quindi una
sostituzione di *contenuto*, documentata in
`audit/results/xg_averages_comparison.md`.

### 1.4 Archivio per-partita: struttura e copertura (dati reali)

| Lega | Record | Stagioni | Concluse | Senza xG (non giocate) | Id duplicati |
|---|---|---|---|---|---|
| Serie A | 1900 | 2022–2026 (380 ciascuna) | 1540 | 360 | 0 |
| Premier League | 1900 | 2022–2026 (380 ciascuna) | 1540 | 360 | 0 |
| La Liga | 1900 | 2022–2026 (380 ciascuna) | 1551 | 349 | 0 |
| Bundesliga | 1530 | 2022–2026 (306 ciascuna) | 1233 | 297 | 0 |
| Ligue 1 | 1604 | 2022 (380) + 2023–2026 (306) | 1317 | 287 | 0 |

* nessuna partita conclusa con xG mancante, nessun id duplicato, nessuna
  coppia `(stagione, casa, trasferta)` ripetuta;
* la stagione corrente 2026/27 è appena iniziata: **20 partite concluse in
  Serie A e Premier, 31 in La Liga, 9 in Bundesliga, 19 in Ligue 1** → 1-3
  partite per squadra;
* i CSV live sono **più avanti** dell'archivio (es. Premier: 27 righe nel CSV
  contro 20 partite concluse nell'archivio). È una differenza di *snapshot*
  fra due fonti aggiornate in momenti diversi, non un errore di mapping.

---

## 2. Cosa cambia

```
                    Understat
                        │
        update_all_xg_db.py   ← UNICA acquisizione (soccerdata)
                        │      validazione + scrittura atomica
                        ▼
    database/xG archivio <lega>.json   (per-partita, 5 stagioni)
                        │
        SoccerMath/update_xg.py        ← nessuno scraping: sola aggregazione
                        │      (SoccerMath/xg_archive.py)
                        ▼
    database/xg_<lega>.json  {"Inter": {"xG_avg", "xGA_avg", "matches"}}
                        │
        scraper_xg.get_understat_xg → app.get_league_engine / elo_engine
                        │
                 shrinkage (PRIOR_MATCHES = 6) — invariato
```

* `SoccerMath/team_names.py` — unica fonte di normalizzazione. Nome canonico =
  `clean_name(nome CSV football-data)`, cioè la chiave con cui
  `get_league_engine` e `elo_engine` indicizzano le squadre. La tabella è
  esplicita e copre **tutti** i 130 titoli Understat presenti negli archivi;
  i nomi sconosciuti non vengono indovinati (nessun fuzzy matching) ma
  segnalati da `resolve_team_name(...).mapped == False`.
  `update_xg.NAME_MAP` resta come alias del dizionario condiviso per
  retrocompatibilità (`audit/test_ng_regression.py` lo usa).
* `SoccerMath/xg_archive.py` — caricamento, validazione e aggregazione
  (`aggregate_season`), riutilizzabile con `cutoff` temporale.
* `SoccerMath/update_xg.py` — comando che deriva `xg_<lega>.json`
  dall'archivio (`--season`, `--cutoff`, `--dry-run`, `--report`).
* `update_all_xg_db.py` — resta l'unica acquisizione, ora con validazione,
  rifiuto degli scrape parziali e scrittura atomica.
* Lo **schema dell'archivio non cambia**: i lettori esistenti
  (`audit/prior_matches_audit.py`, `audit/test_ng_regression.py`,
  `audit/xg_rolling_walkforward.py`) continuano a funzionare. Lo schema delle
  medie cambia solo in aggiunta (`matches`), che `get_league_engine` già
  gestisce.

### Regole di aggregazione

* squadra di casa → `xG = home_xg`, `xGA = away_xg`; ospite → speculare;
* `matches` = partite valide effettivamente incluse per quella squadra;
* solo partite con `is_result` vero e **entrambi** gli xG numerici, finiti e
  ≥ 0; **0.0 è un valore valido**, un dato mancante non diventa mai 0;
* deduplica per `id` (o per `(stagione, casa, trasferta, giorno)` se manca):
  i duplicati identici si contano una volta sola, i **conflitti** (stesso id,
  xG diversi) vengono scartati e riportati, mai mediati;
* una sola stagione per volta: nessuna mescolanza;
* **nessuno shrinkage in aggregazione** — resta in `get_league_engine`;
* squadra senza partite valide → **non** compare nel file (nessuna statistica
  inventata) ed è elencata in `teams_without_valid_matches`: i consumatori
  cadono sul fallback gol già esistente, con lo stesso prior.

### Sicurezza della pubblicazione

* archivio: validazione (schema, date, id duplicati, xG delle partite
  concluse, stagioni attese) **prima** di sostituire il file; rifiuto se il
  nuovo scrape perde più del 10 % delle partite rispetto al precedente;
  scrittura `tmp` + `os.replace`;
* medie: nessuna scrittura se l'archivio manca/non valida o se le squadre con
  partite valide sono meno di 10 (soglia sotto la quale `scraper_xg` e
  `get_league_engine` scartano comunque il file);
* in entrambi i casi l'ultimo insieme valido resta in repo e il comando esce
  con codice ≠ 0.

---

## 3. Workflow

| Prima | Dopo |
|---|---|
| `update_xg.yml`: scarica l'archivio, committa | `update_xg.yml`: **acquisizione → validazione → derivazione medie dallo stesso snapshot → controllo finale → commit** di archivio *e* medie |
| `update_database.yml`: CSV live **+ secondo scraping xG** (`python update_xg.py`, ogni 6 h, `continue-on-error`) | `update_database.yml`: solo CSV live; lo step xG è stato rimosso e `xg_*.json` non è più nel suo `git add` |
| gruppi di concorrenza diversi (`update-database` / nessuno) | stesso gruppo `soccermath-data` per entrambi: non committano mai in parallelo sullo stesso branch |
| `update_xg.yml` senza `permissions` | `permissions: contents: write` esplicito |

Se acquisizione o validazione falliscono, gli step successivi non partono e
non viene committato nulla: restano l'ultimo archivio e le ultime medie valide,
e il workflow fallisce in modo visibile.

---

## 4. Base per audit point-in-time

`aggregate_season(records, season, cutoff=..., cutoff_policy=..., day_timezone=...)`
ricostruisce le medie con le sole partite **dimostrabilmente concluse** prima
dell'istante indicato.

**Criterio predefinito `previous_day` (conservativo).** Entrano solo le partite
dei giorni **strettamente precedenti** a quello del cutoff, nel fuso dichiarato
da `day_timezone` (default UTC). Il giorno della previsione è escluso per
intero **anche quando l'orario di kickoff esiste**: un kickoff alle 18:00 con
cutoff alle 18:30 non dimostra che la partita fosse finita, e l'archivio
contiene `is_result` solo allo **stato odierno**, quindi combinarlo con il
kickoff retrodaterebbe informazione. Non viene assunta nessuna durata fissa
della partita: sarebbe un'ipotesi non verificata e non presente nel dato.

**Criterio `kickoff_unsafe` (opt-in).** Confronto diretto `kickoff < cutoff`.
È più permissivo e **non verificato**: può includere partite ancora in corso.
Va richiesto esplicitamente (`--cutoff-policy kickoff_unsafe`) e i risultati
ottenuti così vanno dichiarati come non validati.

Altre regole (entrambi i criteri):

* il cutoff è timezone-aware; un cutoff naive viene interpretato nel fuso
  dichiarato dell'archivio (`xg_archive.ARCHIVE_TIMEZONE`, UTC);
* `day_timezone` accetta `tzinfo`, nome IANA (`Europe/Rome`) o offset
  (`+02:00`) ed è riportato nel risultato (`day_timezone` in `to_dict()`):
  è una **scelta dichiarata**, non un dato dell'archivio. Esempio verificato:
  kickoff `2026-08-31 22:00` con cutoff `2026-09-01 00:30 UTC` è incluso
  contando i giorni in UTC ed escluso contandoli a Roma;
* se il record ha solo il giorno (o un timestamp `00:00:00`, che Understat non
  usa per un calcio d'inizio reale) vale comunque la regola del giorno intero;
* una data illeggibile con cutoff attivo esclude la partita, non la include
  "per sicurezza";
* le medie vengono **ricalcolate** sulle partite passate: non si filtra un
  totale di fine stagione (test
  `test_cutoff_never_uses_end_of_season_totals`).

### Cosa NON è risolto (limiti residui, dichiarati)

1. **Disponibilità storica reale dei dati Understat.** Ricostruire le medie
   "alla data X" dalle *date delle partite* non equivale a sapere quali dati
   erano *pubblicati* alla data X. Understat rivede gli xG dopo la
   pubblicazione (correzioni sui modelli e sugli eventi) e l'archivio conserva
   solo l'ultimo valore noto: un backtest point-in-time basato su questo
   archivio usa comunque **valori rivisti**. Non ci sono, in questo
   repository, snapshot datati che permettano di verificarlo. Il problema
   resta aperto e non va dichiarato risolto.
2. **Fuso orario dei kickoff.** L'archivio conserva `"YYYY-MM-DD HH:MM:SS"`
   senza offset. È stato scelto UTC come convenzione esplicita, ma non è
   stato possibile verificare il fuso effettivo usato da Understat (vedi §6).
   Per cutoff a granularità di giornata l'impatto è nullo; per cutoff a
   granularità di ora l'incertezza è di ±2 ore.
3. **Ritardo di pubblicazione.** Anche a fuso corretto, l'xG di una partita
   non è disponibile all'istante del fischio finale, e non si sa quanto ci
   metta a comparire. È esattamente il motivo per cui il criterio predefinito
   esclude l'intero giorno del cutoff invece di fidarsi dell'orario di
   kickoff: il criterio `kickoff_unsafe` resta disponibile ma dichiarato come
   non verificato.
4. **Disallineamento fra fonti.** I CSV football-data e l'archivio Understat
   sono aggiornati in momenti diversi (§1.4): un audit point-in-time che
   incrocia le due fonti eredita quella differenza.
5. **Campione della stagione corrente.** A inizio stagione le medie derivate
   poggiano su 1-3 partite: sono corrette ma rumorose, ed è lo shrinkage in
   `get_league_engine` (invariato) a governarne il peso.

Nessun esperimento Poisson/Elo è stato avviato in questo intervento.

---

## 5. Verifiche eseguite

* `SoccerMath/test_xg_pipeline.py` (nuovo): aggregazione casa/trasferta,
  conteggio `matches`, stagione, zero valido/mancanti/negativi/non finiti,
  duplicati e conflitti, alias e collisioni, squadre senza dati, cutoff
  temporale, fallimento dell'acquisizione senza sovrascrittura.
* `audit/test_ng_regression.py`: invariato nella sostanza; l'unica modifica è
  la costruzione **esplicita** dello snapshot "senza Coventry/Hull", perché il
  file xG ora è derivato e contiene anche le neopromosse. Il fix lambda-zero e
  lo shrinkage restano protetti dagli stessi assert.
* `audit/xg_pipeline_audit.py` (nuovo): audit dei nomi sulle 5 leghe e
  confronto delle medie, su dati reali del repository →
  `audit/results/xg_name_audit.md`, `audit/results/xg_averages_comparison.md`.

---

## 6. Impedimenti verificati

* **Nessuna esecuzione reale dello scraper.** Nell'ambiente di sviluppo il
  traffico verso `understat.com` e verso GitHub (download della libreria TLS
  richiesta da `tls_requests`, dipendenza di `soccerdata`) è bloccato:
  `soccerdata.Understat(...)` fallisce con
  `OSError: Failed to download the required TLS library.`.
  È stato quindi verificato **offline**: che `soccerdata` 1.9.1 si installi,
  che `Understat.read_schedule()` esponga esattamente le colonne usate
  (`season_id, game_id, date, home_team, away_team, home_goals, away_goals,
  home_xg, away_xg, is_result`, lette dal sorgente della libreria) e che la
  conversione DataFrame → JSON produca lo stesso schema dell'archivio
  committato (test `test_records_from_schedule_maps_soccerdata_columns`, che
  riproduce i dtype nullable di `convert_dtypes()`).
  L'aggiornamento reale dei dati resta affidato al workflow GitHub Actions.
* **Nessuna modifica a JSONBin** e nessuna credenziale toccata.

---

## 7. Secondo giro: quattro correzioni verificate

Interventi successivi alla prima consegna (`e23c807`), nati dalla revisione
puntuale di quel commit. Nessuna modifica a formule predittive, `PRIOR_MATCHES`,
pesi Poisson/Elo, versione del modello o JSONBin.

### 7.1 Il cutoff includeva partite ancora in corso

*Problema.* Il criterio `kickoff < cutoff` combinato con `is_result` (che è lo
stato **odierno**) faceva entrare, in una ricostruzione al 5 settembre ore
18:30, una partita iniziata alle 18:00 e finita alle 19:50.

*Correzione.* Nuovo criterio predefinito `previous_day` descritto in §4, più
`day_timezone` esplicito. Il vecchio comportamento resta disponibile solo come
`kickoff_unsafe`, documentato come non verificato. Nessuna durata fissa della
partita è stata introdotta.

*Test* (`SoccerMath/test_xg_pipeline.py`, classe `TestTemporalCutoff`):
partita in corso all'istante del cutoff, partita dello stesso giorno iniziata
prima, partita del giorno precedente, confine di fuso UTC vs `Europe/Rome`,
offset numerico, opt-in `kickoff_unsafe` e suo fallback alla regola del giorno
quando manca l'orario, rifiuto di una policy sconosciuta.

### 7.2 Protezione dagli archivi parziali basata sul solo totale

*Problema.* `MAX_SHRINK_RATIO` guardava il numero complessivo di righe delle 5
stagioni: uno snapshot con lo **stesso** numero di partite ma con un risultato
sostituito, o con una singola partita conclusa mancante, passava il controllo.

*Correzione.* `xg_archive.compare_snapshots()` confronta i due snapshot
**partita per partita**, con chiave `(stagione, id)` (fallback
`(stagione, casa, ospite)` per archivi senza id). Bloccano:

* partite **concluse con xG valido** presenti nel vecchio snapshot e assenti
  dal nuovo;
* partite regredite da conclusa-con-xG a non giocata / senza xG;
* stagioni con risultati scomparse, salvo `--allow-dropping-seasons`.

Restano ammesse e vengono riportate: partite nuove, correzioni di xG sulla
stessa partita (Understat rivede i valori), fixture **non giocate** tolte dal
calendario. La soglia sul volume rimane come rete secondaria, ma calcolata solo
sulle stagioni richieste. Un fallimento non scrive l'archivio e, poiché il
workflow interrompe la catena, non pubblica nemmeno le medie.

*Test* (`TestAcquisitionSafety`, `TestSnapshotDiff`): una sola partita conclusa
mancante su 200, stesso totale con un id sostituito, conclusa → non giocata,
nuove partite + correzioni xG + fixture rimossa (accettate), riduzione di
stagione con e senza flag, perdita di risultati in una stagione ancora
richiesta anche con il flag attivo, `--baseline-dir` che confronta con i dati
veri scrivendo altrove.

### 7.3 I nomi non risolti non bloccavano la pubblicazione

*Problema.* `derive_league()` scriveva `xg_<lega>.json` e solo dopo `main()`
stampava un warning sui nomi non mappati: un titolo Understat cambiato finiva
pubblicato con il nome grezzo e l'engine cadeva in silenzio sul fallback gol.

*Correzione.*

* `update_xg.mapping_errors()` viene chiamata **prima di qualunque
  scrittura**: nomi non risolti o collisioni non dichiarate fanno fallire la
  lega lasciando intatto il file precedente (uscita ≠ 0);
* `team_names.resolve_team_name()` restituisce ora anche `source`
  (`alias` | `canonical` | `unknown` | `empty`): i nomi **già canonici** sono
  accettati esplicitamente, quindi nessun falso allarme e nessun fuzzy
  matching. `.mapped` resta per compatibilità;
* le collisioni legittime vanno dichiarate in `update_xg.ACCEPTED_COLLISIONS`
  (oggi vuoto: sui dati reali non ce n'è nessuna);
* `--allow-unmapped-names` esiste solo come uscita di emergenza manuale e
  declassa gli errori a warning; il workflow non lo usa.

*Fonte unica degli alias.* Le tabelle ancora sovrapposte
(`config.TEAM_NAME_MAP` + `clean_name` da una parte, gli alias di
`team_names.py` dall'altra) sono confluite in **`SoccerMath/team_aliases.py`**,
modulo senza dipendenze dal progetto (quindi nessun import circolare):
`TEAM_NAME_MAP`, `NAME_CLEAN_REPLACEMENTS`, `clean_name()`,
`UNDERSTAT_NAME_MAP`, `ALL_ALIASES`, `CANONICAL_NAMES`. `config.py` li
ri-esporta (`from config import clean_name`, `config.TEAM_NAME_MAP` continuano
a funzionare) e `team_names.py` contiene ora solo il resolver.
Nel travaso sono stati corretti due valori non canonici di `config`:
`FC St. Pauli → St Pauli` (era `St. Pauli`) e
`AS Saint-Étienne → St Etienne` (era `Saint-Etienne`); entrambi puntavano a
nomi che i CSV non usano.

*Test* (`TestSharedAliasSource`, `TestBlockingNameValidation`): nome
sconosciuto che blocca, alias valido accettato, nome canonico accettato senza
warning, collisione non dichiarata che blocca, collisione dichiarata ammessa,
file precedente invariato dopo l'errore (nessun `.tmp` lasciato in giro),
coerenza fra i due livelli (`conflicting_aliases() == {}`), ogni valore
mappato è canonico, ogni nome dei CSV delle 5 leghe è già canonico, i cinque
archivi reali passano la validazione bloccante.

*Audit rieseguito*: `audit/results/xg_name_audit.md` → **482/482** coppie
(lega, stagione, squadra) risolte, **0** non risolte, **0** collisioni; i nomi
prima marcati "no (solo clean_name)" (`Dortmund`, `Leipzig`, `Stuttgart`,
`Ath Bilbao`, `St Etienne`) risultano ora riconosciuti come **canonici**.
Le medie derivate dopo il refactor sono **identiche byte per byte** a quelle
già committate.

### 7.4 Modalità verifica su GitHub Actions (dati reali)

Nuovo workflow **`.github/workflows/xg_verify.yml`** — *Verifica pipeline xG
(solo lettura)*:

1. installa `soccerdata==1.9.1` (versione dichiarata; `update_all_xg_db.py`
   controlla a runtime la versione effettiva e lo scrive nei log) e `pandas`;
2. esegue i test offline della pipeline;
3. **acquisizione reale** delle 5 leghe con output in `$RUNNER_TEMP` e
   `--baseline-dir SoccerMath/database` (il confronto per-partita di §7.2 usa
   i dati veri);
4. deriva le medie dallo stesso snapshot nella cartella temporanea, con la
   validazione bloccante dei nomi di §7.3;
5. riesegue l'audit nomi/medie con `--database-dir` e `--results-dir`
   temporanei;
6. verifica con `git diff --exit-code` che **nessun** file committato sia
   cambiato e pubblica archivio, medie e report come artifact.

`permissions: contents: read`, nessun commit, nessun push, nessun segreto:
JSONBin e `main` non vengono toccati.

Come avviarlo a mano da GitHub web (il `push` su `arena/**` lo avvia già da
solo, e il pulsante *Run workflow* compare solo dopo che il file esiste sul
branch di default):

1. `Actions` → workflow **Verifica pipeline xG (solo lettura)**;
2. `Run workflow` → **Branch: `arena/01a071f5-soccermath2-0`** → `Run workflow`;
3. a fine run, scaricare l'artifact `xg-verify-<run_id>`.

In alternativa da CLI:
`gh workflow run xg_verify.yml --ref arena/01a071f5-soccermath2-0`
(funziona solo dopo che il workflow è presente sul branch di default; fino ad
allora vale l'esecuzione automatica innescata dal push).

I test offline **non** sono una prova di acquisizione reale: la prova è il run
di questo workflow.

### 7.5 Limiti residui dopo il secondo giro

* Gli **xG rivisti** restano un limite non risolvibile con questo archivio
  (§4, punto 1): la ricostruzione point-in-time usa gli ultimi valori noti.
* Il **fuso reale dei timestamp Understat** non è documentato nel dato: `UTC`
  è una convenzione dichiarata, `day_timezone` serve a renderla esplicita.
* `compare_snapshots()` protegge dalle perdite, non dalla **correttezza** dei
  valori: se Understat pubblicasse xG sbagliati ma coerenti, il confronto li
  accetterebbe come "correzioni".
* La validazione dei nomi vede solo i nomi **presenti** nello snapshot: una
  squadra che sparisce del tutto dall'archivio non genera un errore di
  mapping (genera semmai una partita mancante, coperta da §7.2).
* L'ambiente di sviluppo continua a non poter contattare Understat (§6):
  ogni verifica su dati veri passa da GitHub Actions.
