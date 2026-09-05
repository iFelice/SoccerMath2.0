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

`aggregate_season(records, season, cutoff=...)` include **solo** le partite
concluse prima dell'istante indicato:

* il cutoff è timezone-aware; un cutoff naive viene interpretato nel fuso
  dichiarato dell'archivio (`xg_archive.ARCHIVE_TIMEZONE`, UTC);
* una partita esattamente **all'istante** del cutoff è esclusa;
* se il record ha solo il giorno (o un timestamp `00:00:00`, che Understat non
  usa per un calcio d'inizio reale) si esclude **l'intero giorno** del cutoff;
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
   non è disponibile all'istante del fischio finale. Il cutoff a livello di
   partita è quindi ottimistico di qualche decina di minuti; per audit
   prudenti conviene usare un cutoff a inizio giornata.
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
