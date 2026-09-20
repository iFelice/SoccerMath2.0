# Replay Top Mix a due modelli — referto unico delle due commesse

Un solo referto per **due comandi** che insieme coprono tutta la storia
ricostruibile, senza sovrapporsi:

| commessa | finestra | comando |
|---|---|---|
| **simmetrico** (questa) | dal primo istante ricostruibile al merge di PR#24 | `--from 2026-08-30 --to 2026-09-18 --from-instant 2026-08-30T11:27:06Z --to-instant 2026-09-18T21:51:58Z --model both` |
| **legacy** (precedente) | dal merge di PR#24 a oggi | `--from 2026-09-18 --to oggi --from-instant 2026-09-18T21:51:58Z --model both` |

Entrambi girano sul **medesimo** codice (`SoccerMath/replay_legacy_topmix.py`):
ogni click replica **entrambi** i modelli sullo stesso snapshot, con lo stesso
cutoff xG e lo stesso pool; nel Registro entra una riga per modello, con la sua
`model_variant` (`current` / `legacy`), struttura identica, **mai** una
sovrascrittura.

---

## 1. Fin dove si torna indietro, e perché proprio lì

**Dichiarato e misurato, non stimato.**

* `REPLAY_START_INSTANT = 2026-08-30T11:27:06Z` = data di committer del commit
  `48e7768`, il **primo** commit di `main` in cui i CSV live contengono la
  stagione 2026/27. Prima di quel commit in git c'è un'altra stagione (e fino al
  26/08/2026 la cartella dati sta pure nel vecchio percorso `database/`): un
  replay di quelle partite darebbe al modello un database vecchio di un anno,
  cioè **non** il modello che era live.
* La finestra **non dipende da questa costante**: la guardia
  `snapshot_covers_season` (per click e per lega) verifica sui fatti che la
  cartella dati dello snapshot parli della stagione giusta. Un click che non la
  supera **non produce righe** e finisce nel referto come controprova.
  Verifica del confine (run del 15→29/08): tutti i click prima del 30/08
  falliscono la guardia → 0 righe scritte, e il referto lo dice.
* `PR24_MERGE_INSTANT = 2026-09-18T21:51:58Z`: il confine fra le due commesse è
  **l'istante**, non il giorno. Con i soli giorni la partita del 18/09 sarebbe
  finita in entrambe le commesse: `--from-instant`/`--to-instant` introducono il
  semintervallo `[inizio, fine)`. Test: `TestFinestraComplementare`
  (`test_replay_legacy_no_leakage.py`) verifica che nessuna partita stia in
  entrambe e che l'unione delle due finestre sia tutto il periodo.

## 2. Requisito per requisito

| # | richiesta | come | prova |
|---|---|---|---|
| 1 | periodo = partite **prima** di PR#24, complementare, senza sovrapposizione; dichiarare il limite di storia | finestre a istante (§1) | `TestFinestraComplementare`; finestra stampata nel referto |
| 2 | rigiocare il **modello attuale** (post-fix) su quelle partite con la stessa regola ferrea | `--model both`: un click, due motori | `leak_ok` in ogni referto; `TestSnapshotPointInTime`, `TestPositiveControl`, `TestDueModelliStessoClick` |
| 3 | scrivere le righe del modello attuale dove oggi ci sono solo righe legacy | `--write` al Registro con `model_variant=current` | sezione «Registro» dei referti; `TestRegistryMerge` (mai sovrascritture, idempotenza) |
| 4 | verifica finale: entrambi i modelli per ogni partita, campioni della stessa lunghezza | `registry_coverage_check.py` (sola lettura) + sezione «Copertura» | §4: **61 partite con entrambi**, 9 solo attuale, 0 solo legacy — dichiarate una per una |
| 5 | stessa suite completa, stesso fetch+diff, stessa PR | suite intera, `git fetch`+diff, PR esistente aggiornata | §6 |

## 3. La regola ferrea (no-leakage), riusata identica

Ogni ricostruzione nasce dallo snapshot di `main` all'istante **kickoff − 1 s**,
mai da dati successivi. Il test esplicito non si fida della logica e verifica
quattro cose **più** la finestra:

1. il commit dello snapshot **precede** l'istante del click;
2. il risultato della partita **non è** nei CSV live dello snapshot;
3. il risultato della partita **non è** nell'archivio xG dello snapshot;
4. `season_point_in_time_averages` è stata chiamata con **quell'unico** cutoff;
5. (guardia separata) la cartella dati dello snapshot descrive la stagione
   giusta, altrimenti il click non è scrivibile.

Esito su **entrambe** le finestre e su entrambe le sorgenti di fixture:
`Leak check complessivo: OK · finestra dichiarata ricostruibile: OK`, con
**ogni** click scrivibile (0 click non scrivibili).

Controprova positiva: `TestPositiveControl` costruisce un repo avvelenato e
dimostra che il test di leakage **sa fallire** quando il risultato è davvero
visibile allo snapshot.

## 4. I numeri

### 4.1 Offline (fixture dai CSV/archivio del repo; referti versionati)

| finestra | click | righe Attuale | righe Legacy | partite con entrambi | solo Attuale | solo Legacy |
|---|---|---|---|---|---|---|
| simmetrico 30/08 → merge PR#24 | 82 (82 scrivibili) | 61 | 53 | 53 | 8 | 0 |
| legacy merge PR#24 → 20/09 | 10 (10 scrivibili) | 9 | 8 | 8 | 1 | 0 |
| **unione** (copia fusa, 131 righe) | 92 | **70** | **61** | **61** | **9** | **0** |

La riga «unione» è la prova che la partizione è esatta: unendo i due referti
complementari si ottengono **esattamente** gli stessi numeri del run unico
sull'intero periodo (70 / 61 / 61 / 9) — nessuna partita persa, nessuna contata
due volte.

### 4.2 CI su dati veri (fixture football-data.org, sola lettura)

| run | click | righe Attuale | righe Legacy | entrambi | solo Attuale | solo Legacy |
|---|---|---|---|---|---|---|
| intero periodo 30/08 → 20/09 | 101 | 75 | 66 | 66 | 9 | 0 |
| simmetrico (tag `replay-check-sym-2026-09-20`) | 80 | 60 | 52 | 52 | 8 | 0 |

Stesso schema delle due sorgenti (le differenze di qualche unità sono partite
che l'archivio CSV non ha e l'API sì): **sempre 0 partite solo-legacy**, e il
numero di partite solo-attuale è dello stesso ordine.

La terza run CI (finestra legacy, tag `replay-check-legacy-2026-09-20`) è stata
**avviata** ed è quella che chiude il conto con i numeri dell'API; la sua lettura
è rimasta in sospeso per un problema di autenticazione su GitHub (token della
sessione non più valido), non per un errore del run.

### 4.3 Le 9 partite coperte da un solo modello: misurate, non ipotizzate

`audit/diagnose_scarti_model_variant.py` esegue per ognuna un **click vero**,
intercetta gli ingressi del selettore mentre gira e nomina il motivo con
`app.riga_top_mix_shadow`; se la matematica «ombra» non coincide con la riga
vera nei casi selezionati, la diagnosi **fallisce** invece di stampare numeri
plausibili. Referto: `audit/results/replay_sym_offline/diagnosi_scarti.md`.

| partita | presente | assente: motivo |
|---|---|---|
| Aston Villa - Arsenal (Premier, 31/08) | Attuale 2 56,3% | sotto soglia 0,527 < 0,55 |
| Betis - Real Madrid (La Liga, 04/09) | Attuale 2 55,3% | sotto soglia 0,519 < 0,55 |
| Ipswich - Liverpool (Premier, 04/09) | Attuale 2 71,4% | **veto** (disaccordo ≥ 0,25) |
| Werder Bremen - Leipzig (Bundesliga, 05/09) | Attuale 2 57,6% | sotto soglia 0,545 < 0,55 |
| Freiburg - M'gladbach (Bundesliga, 12/09) | Attuale 1 60,3% | sotto soglia 0,525 < 0,55 |
| Real Madrid - Vallecano (La Liga, 12/09) | Attuale 1 77,9% | **veto** (disaccordo ≥ 0,25) |
| Torino - Roma (Serie A, 14/09) | Attuale 2 63,3% | sotto soglia 0,540 < 0,55 |
| Elche - Real Madrid (La Liga, 15/09) | Attuale 2 76,2% | **veto** (disaccordo ≥ 0,25) |
| Nottingham Forest - Coventry (Premier, 19/09) | Attuale 1 58,8% | sotto soglia 0,548 < 0,55 |

**6 sotto soglia, 3 veto.** In tutti e 9 i casi il modello assente è il
**legacy**, mai l'attuale: l'Elo legacy (che porta il boost xG retroattivo) si
allontana dal Poisson più di quello attuale, quindi o supera il veto o porta la
confidence appena sotto 0,55. Il selettore è lo stesso, le soglie sono le
stesse (0,55 1X2 / 0,60 Totali): **non** una svista, non un buco.

**Dichiarazione esplicita.** La richiesta «i campioni devono coincidere, stessa
lunghezza per entrambi i modelli» **non può essere soddisfatta** su questo
periodo senza toccare le regole di produzione: per quelle 9 partite il modello
legacy non esprime alcuna scelta, e il Registro non inventa una riga per far
tornare il conto. Le vie che l'avrebbero fatta tornare — abbassare le soglie,
scrivere righe sotto soglia, marcare quelle partite — sono state **scartate**:
violano la consegna «struttura identica, nessuna etichetta speciale, soglie
invariate» e falserebbero il campione. Il numero vero è: **61 partite giocate
da entrambi i modelli** (66 sui dati API), **9 solo dall'attuale**, **0 solo dal
legacy**. Chi vuole l'uguaglianza deve cambiare le regole del selettore, non il
replay: la misura è pronta per dirlo.

## 5. Scrittura nel Registro

* Cosa entra: per ogni partita della finestra, **una** riga per modello
  (`current` e `legacy`), prodotta dalla stessa catena del click live
  (`argomenti_registro_top_mix` → `build_prediction_entry` → grading), con
  `snapshot_sha` dello snapshot usato e `salvato_il` dell'istante del click.
  Nessun campo diverso, nessuna etichetta.
* Come entra: `merge_entries` aggiunge **solo chiavi nuove**. Chiave di dedup =
  `(match_id, origin, selector_version, model_variant)`: una riga scritta da un
  click vero **non** viene mai riscritta né aggiornata, e rilanciare il replay è
  idempotente (`gia_presente`). `TestRegistryMerge` lo verifica, byte per byte
  sulla parte preesistente.
* Il Registro remoto è caricato in modo **stretto** (GET 200 obbligatorio):
  se il remoto non risponde o è vuoto la scrittura si **rifiuta** invece di
  scrivere sopra. Con `--write`, qualunque esito diverso da «scritto» o «non
  c'era nulla da aggiungere» fa uscire **1** (`scrittura_fallita`, 5 test):
  un errore non può più passare per un verde.
* Le due finestre si scrivono con **due tag**, che sono il comando:
  `replay-write-sym-<data>` e `replay-write-legacy-<data>`. Da un push di
  branch il workflow resta **sempre** dry-run.

> **Blocco attuale (non aggirabile da qui).** Il passo `mode=write` esce subito
> con: `mode=write richiede JSONBIN_API_KEY e JSONBIN_BIN_ID.` I due secret **non** sono configurati: senza, la CI non può né scrivere
> né leggere il Registro live (il controllo di copertura legge 0 righe e lo
> dichiara: `Registro (nessun registro)`). Nessuna riga è stata scritta finora.
> Per sbloccare: aggiungere i due secret in *Settings → Secrets and variables →
> Actions*, poi ripushare i due tag di scrittura.

## 6. Verifiche eseguite

* **Suite completa**: `818 passed, 1006 subtests passed` (`SoccerMath/` +
  `audit/`, con `test_theme_toggle.py` a parte: `🎉 TUTTI I TEST PASSATI`).
  Nessun test saltato, nessun sottoinsieme.
* Nuovi test in questa consegna: finestre complementari a istante (4),
  fedeltà per variante (4), esito della scrittura (5), registro da file (3),
  ritentativi del fetch (4), più le classi del doppio modello già esistenti.
* **CI su dati veri** (`gh run watch`): run dry-run verde sull'intero periodo e
  sul solo periodo simmetrico; i numeri sopra arrivano dalle **annotazioni** del
  run, leggibili senza scaricare artifact.
* **Fetch + diff**: i due comandi girano contro `origin/main` con la storia
  completa (gli snapshot vengono da git), e il referto dichiara il ref usato.

## 7. Cosa resta aperto

1. **Secret JSONBin** → sbloccano scrittura e verifica di copertura sul Registro
   live (punto §5 e requisito 4 «sul Registro»).
2. Le **9** partite solo-attuale: dichiarate, spiegate, non forzate (§4.3).
   È l'unico punto che richiede una decisione: l'uguaglianza dei campioni
   esiste solo cambiando le regole del selettore, non il replay.
3. 2 kickoff incerti (Levante-Ath Bilbao, Monaco-Lens) e 14 click con snapshot
   privo dell'archivio xG (arriva in git il 01/09): entrambe dichiarate nel
   referto, con il fallback che userebbe la produzione con quegli stessi dati.

## 8. Dove stanno le prove

| file | cosa |
|---|---|
| `audit/results/replay_sym_offline/replay_legacy_topmix.md` + `.json` | referto completo della finestra simmetrica (offline) |
| `audit/results/replay_legacy_topmix_offline/replay_legacy_topmix.md` + `.json` | referto completo della finestra legacy (offline) |
| `audit/results/replay_sym_offline/registro_offline_fuso.json` | unione delle due finestre (131 righe) |
| `audit/results/replay_sym_offline/coverage_unione.json` | copertura dell'intero periodo sull'unione |
| `audit/results/replay_sym_offline/diagnosi_scarti.md` | le 9 partite, motivo misurato |
| `audit/diagnose_scarti_model_variant.py` | lo strumento che le misura |
| `.github/workflows/replay_legacy_topmix.yml` | i due comandi (tag = comando), dry-run di default |
