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
| simmetrico (tag `replay-check-sym-2026-09-20`) | 80 | 60 | 52 | 52 | 8 | 0 |
| legacy (tag `replay-check-legacy-2026-09-20`) | 21 | 15 | 14 | 14 | 1 | 0 |
| **somma delle due finestre** | 101 | **75** | **66** | **66** | **9** | **0** |
| intero periodo in un solo run (push su branch) | 101 | 75 | 66 | 66 | 9 | 0 |

La somma delle due finestre complementari dà **esattamente** i numeri del run
unico sull'intero periodo — 60+15 = 75, 52+14 = 66, 8+1 = 9 — su dati API veri,
non su una ricostruzione: la partizione a istante è esatta anche in CI.
Stesso schema delle due sorgenti di fixture (le differenze di qualche unità sono
partite che l'archivio CSV del repo non ha e l'API sì): **sempre 0 partite
solo-legacy**, e 9 partite solo-attuale sull'intero periodo.

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

### 4.4 Il Registro vero, dopo le scritture: la copertura dei due modelli (misurata, ripetibile)

I numeri dei paragrafi precedenti dicono cosa il replay **scrive**; questa
sezione dice cosa il Registro **contiene adesso**, lettura pura, e risponde una
per una alle richieste della commessa. Lo strumento e'
`SoccerMath/registry_modelli_check.py` (sola lettura: nessuna scrittura di
registro, nessuna PUT/HSET): partiziona il Registro sulla **stessa** finestra
ricostruibile (`REPLAY_START_INSTANT` = `2026-08-30T11:27:06Z`) e sullo **stesso**
confine di PR#24 (`PR24_MERGE_INSTANT` = `2026-09-18T21:51:58Z`, half-open),
**importati** dal codice del replay invece che ricopiati, e per ogni partita
guarda se esiste la riga del modello attuale, quella del legacy, o entrambe.

| sezione | righe in finestra | di cui del replay (variante esplicita) | di cui click veri dell'epoca (campo assente) | partite attuale | partite legacy | con entrambi | solo attuale | solo legacy |
|---|---|---|---|---|---|---|---|---|
| VECCHIO (prima di PR#24) | 138 | 98 | 40 | 70 | 52 | 52 | 18 | **0** |
| NUOVO (da PR#24 in poi) | 33 | 27 | 6 | 17 | 16 | 16 | 1 | **0** |
| **INTERO PERIODO** | **171** | **125** | **46** | **87** | **68** | **68** | **19** | **0** |

Fonte: Registro vivo (hash Upstash `sm:registro`), lettura del
21/09/2026 nel run `35570242579` (tag `verifica-modelli-upstash-2026-09-21`).
Il workflow `verifica_modelli.yml` lo rifà a ogni push del tag e pubblica i
numeri come **annotazioni** della run: si leggono senza scaricare artefatti.
Le due colonne «del replay» e «click veri» servono a non confondere le specie:
prima di PR#24 il campo `model_variant` non esisteva, e la convenzione legge le
righe senza campo come `current` — ma quelle righe non le ha scritte il replay.

**Il campione è simmetrico per costruzione, e i numeri lo dicono.** Ogni partita
che il legacy copre ha **anche** la riga dell'attuale (`solo legacy = 0`, sia
nella sezione vecchia sia in quella nuova): non c'e' una sola partita in cui il
modello vecchio abbia scelto e il nuovo sia assente. E' esattamente la richiesta
«per la stessa partita dove esistono righe legacy, le righe attuali devono
esserci»: soddisfatta, e verificabile a comando.

**Il gate e' onesto: rosso solo per l'attuale.** Il passo di CI esce **rosso**
(errore, non warning) se manca una riga del modello **attuale** per una partita
che il legacy copre: quella e' copertura incompleta di cio' che la commessa
chiedeva di rigiocare, e si ripara rilanciando il replay (che aggiunge, non
sovrascrive). Le righe legacy mancanti invece **si dichiarano** e la run resta
verde: quelle righe non si scrivono, perche' il legacy li' non esprime alcuna
scelta e inventarla falserebbe il campione. Sul Registro vero il gate dice:
**righe ATTUALE mancanti 0 · righe LEGACY mancanti 19**.

| esito del gate | valore sul Registro vero |
|---|---|
| righe ATTUALE mancanti (rosso) | **0** |
| righe LEGACY mancanti (verde, dichiarate) | **19** |
| esito run | **success** |

**Le 19 partite solo-attuale: causa misurata, non ipotizzata.** Lo stesso
strumento di diagnosi (`audit/diagnose_scarti_model_variant.py`, ora con
`--fixtures api` perche' gli id sintetici dei CSV non sono quelli veri del
Registro) rigioca **ognuna** delle 19 con un click vero e legge il motivo dal
selettore: `NON DIAGNOSTICABILI: 0 su 19` — nessuna riga e' rimasta senza
spiegazione. Riepilogo della run: **sotto soglia 16 · veto 3**. Le soglie sono
quelle di produzione, invariate (0,55 1X2 / 0,60 Totali): i casi di confine
stanno **appena** sotto e sono dichiarati tali — Alavés–Osasuna 0,600 (Totali)
e Under 2.5 a 0,598, Brighton–Leeds Over 2.5 0,546, fino al minimo 0,520.
Nessuna riga sotto soglia e' stata scritta: e' la regola della commessa, ed e'
la ragione per cui i due campioni non hanno la stessa lunghezza.

**Perche' i numeri non sono quelli dei dry-run (§4.1–4.2).** I dry-run misuravano
i due comandi alla data di quei run; la finestra legacy arriva a **oggi**, quindi
ogni giornata di campionato conclusa aggiunge partite a entrambi i modelli (era
21 click, poi 23...). Non e' instabilita' del replay: e' il calendario. La
verifica qui sopra e' una fotografia datata e si puo' rifare identica.

**Le due specie di riga, contate.** Delle 19 partite solo-attuale: **9** sono
coperte da una riga del **replay** (variante esplicita), **11** da un **click
vero dell'epoca** (campo assente); una partita (Ipswich–Liverpool) ha entrambe.
Non sono quindi 19 righe scritte dal replay: sono 19 partite, con la riga che
l'attuale ha davvero — e la distinzione e' scritta nel referto e nel JSON
(`riga_del_replay` / `riga_storica` per ogni voce), non lasciata all'ambiguita'
della convenzione.

**Dichiarazione esplicita, di nuovo.** L'uguaglianza «stesso campione, stessa
lunghezza per i due modelli» resta **non soddisfatta** sui dati veri: 68 partite
giocate da entrambi, 19 solo dall'attuale, 0 solo dal legacy. Le vie per farla
tornare (abbassare le soglie, scrivere le righe sotto soglia, etichettare le
partite) restano **scartate**: violano la consegna e falsano il campione. Il
conto e' pronto, ripetibile, e non nasconde niente.

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

### Il PUT remoto si ferma sul tetto del piano free JSONBin (misurato) — e come e' stato superato

> **Esito.** Il muro descritto qui sotto e' stato superato **senza pagare**:
> il Registro vive ora su **Upstash** (REST, un hash, una riga = un campo, una
> `HSET` per riga), con uno strato di accesso unico (`registry_store.py`) e la
> scelta del backend per configurazione (`REGISTRY_BACKEND`); JSONBin resta
> intatto come **archivio dichiarato**, non si tocca piu'. Referto dedicato:
> `audit/results/migrazione_registro_upstash.md` (fasi A–E, verifica in sola
> lettura prima di ogni scrittura, idempotenza, fallback di sharding se mai
> servisse). Il testo che segue resta come **misura** del muro, non come stato
> attuale.

I secret sono configurati (la **lettura** remota infatti funziona: `fonte:
jsonbin`, 108 righe). La **scrittura** arriva fino al PUT e viene **respinta dal
servizio**, con la risposta letta verbatim dal corpo HTTP:

```
HTTP 403: {"message":"Free users cannot update a record over 100kb.
           Upgrade to Pro plan http://api.jsonbin.io/pricing to update records upto 1mb"}
payload 140353 byte, fusione 206 righe
```

Aritmetica del limite (numeri misurati, non stimati):

| voce | valore |
|---|---|
| payload respinto (registro live 108 righe + 98 righe del replay simmetrico) | **140.353 byte** |
| costo medio per riga (140.353 / 206) | ~681 byte |
| registro live attuale (108 righe x 681) | **~74 kB** |
| tetto del piano free | **100 kB** |
| spazio residuo prima che si blocchino anche i salvataggi dell'app | **~26 kB, ~38 righe** |

Conseguenze, in ordine di importanza:

1. **Il replay non entra**: la finestra simmetrica da sola vuole ~98 righe nuove,
   la finestra legacy altre ~29. Anche solo la prima porta il registro a ~140 kB,
   oltre il tetto: il servizio rifiuta l'aggiornamento intero (non e' un rifiuto
   parziale).
2. **Riguarda anche la produzione, non solo il replay**: il registro e' una
   singola "record" JSONBin, quindi *ogni* salvataggio dell'app riscrive tutto.
   A ~74 kB su 100 kB, fra una quarantina di righe (due giornate circa) **anche i
   salvataggi del click vero dell'app** verrebbero respinti con lo stesso 403, e
   resterebbero solo in locale.
3. Il comportamento e' gia' quello giusto: nessun verde bugiardo. `--write` esce
   **1** e il referto dice `PUT remoto non riuscito`, con byte e risposta del
   servizio (`remoto_dettaglio`, `byte_scritti`, `byte_payload`).

Cosa serve per chiudere il requisito 3 (scrittura), in ordine di costo:

* **(a) passare JSONBin a un piano a pagamento** (1 MB per record): nessuna
  modifica di codice, i due tag di scrittura completano entrambe le finestre;
* **(b) ripartire lo storage** (un bin per stagione o per variante, con lettura
  che li unisce): resta il piano free, ma e' una modifica al percorso di
  lettura/scrittura dell'app, non solo del replay;
* (c) scrivere solo le righe che entrano nel tetto: possibile, ma lascia i
  campioni incompleti **e** porta il registro a ridosso del limite, quindi non
  risolve il problema 2. Sconsigliato.

Nessuna riga e' stata scritta finora: nessun effetto collaterale da annullare.

## 5bis. Il replay rifa' i click veri? (verifica diretta)

La sezione «Fedelta'» confronta le righe del Registro con quelle ricostruite, ma
il confronto e' severo **per costruzione**: le righe del Registro sono state
scritte quando l'utente ha premuto il bottone (dati di allora, "prossima
giornata" di allora), il replay ricostruisce a **kickoff - 1 s**. Se i due
istanti cadono in giorni diversi, il dato e' diverso e i numeri **devono**
differire.

Per togliere il dubbio, `audit/verifica_click_live.py` ricostruisce il click
**all'istante del salvataggio** (`salvato_il`, in ora italiana) e confronta:
prima di PR#24 col modello legacy (era quello live), dopo con la variante
dichiarata. Se nessuna riga coincide, il comando **esce 1**: vuol dire che il
metodo non riproduce la realta', non che i numeri sono diversi.

* controllo positivo in locale: righe salvate allo stesso istante della
  ricostruzione -> **3/3 coincidono** (lo strumento misura davvero);
* campione sul Registro vero (tag `replay-check-sym-2026-09-20`): 46 righe Top
  Mix nel periodo, 6 verificate (3 prima di PR#24, 3 dopo).

| riga | salvata il | motore di allora | nel Registro | ricostruzione | esito |
|---|---|---|---|---|---|
| Stuttgart - Dortmund | 15/09 17:18 | Attuale | GG 68% | GG 68.0% | **coincide** |
| Schalke - Elversberg | 15/09 17:18 | Attuale | OVER_2.5 70.6% | OVER_2.5 70.6% | **coincide** |
| Man City - Sunderland | 15/09 17:18 | Attuale | 1 72.2% | 1 76.3% | stesso mercato, probabilita' diversa |
| Ipswich Town - Liverpool | 04/09 15:25 | Legacy | 2 80.3% | non riselezionata | vedi sotto |
| Man City - Coventry | 04/09 15:25 | Legacy | NG 99.8% | 1 78.9% | vedi sotto |
| Hull City - Aston Villa | 04/09 15:25 | Legacy | NG 99.8% | non riselezionata | vedi sotto |

Le tre righe del 04/09 15:25 hanno una spiegazione **datata**, non un'ipotesi:
due portano **`NG 99.8%`**, che e' la firma del bug del prior NG (lambda ~0 per le
neopromosse), e il fix e' il commit `ae8784d` del **2026-09-04 15:40:10Z**, cioe'
**due ore e mezza DOPO** il salvataggio di quelle righe (15:25 ora italiana =
13:25Z). Il replay rifa' il modello di **oggi**, fix compreso: non puo' riprodurre
un numero sbagliato che il codice ha smesso di produrre. La terza differenza (Man
City - Sunderland) e' lo stesso mercato con probabilita' diversa: il click vero
uso' il database di quel momento, la ricostruzione il commit `e1ee3719ca06`, e
fra i due c'e' un aggiornamento dei dati.

**Conclusione onesta**: dove l'istante e la versione del codice coincidono la
ricostruzione riproduce il click vero (2 righe su 3 esatte al decimo di punto);
dove non coincidono il motivo e' identificato e dichiarato (dato aggiornato,
oppure bug corretto dopo). E' anche la spiegazione del `13/80` della sezione
«Fedelta'»: le righe storiche non sono confrontabili con il motore di oggi, ed e'
proprio il motivo per cui la commessa chiede di **rigiocare** quelle partite.

Nota di metodo: una prima versione di questa verifica e' morta in CI su una
funzione inesistente (`check._nel_periodo`, che sta in `registry_coverage`)
lasciando il passo **verde**: la pipe senza `pipefail` inghiottiva l'errore. Ora
il passo ha `set -o pipefail`, stampa sempre le ultime righe, e un test
end-to-end su registro finto copre quel percorso.

## 6. Verifiche eseguite

* **Suite completa**: `907 passed, 1006 subtests passed` (`SoccerMath/` +
  `audit/`, con `test_theme_toggle.py` a parte: `🎉 TUTTI I TEST PASSATI`).
  Nessun test saltato, nessun sottoinsieme.
* Nuovi test in questa consegna: finestre complementari a istante (4),
  fedeltà per variante (4), esito della scrittura (5), registro da file (3),
  ritentativi del fetch (4), più le classi del doppio modello già esistenti.
  Alla verifica dei due modelli si aggiungono: pareggio/mismatch, confine a
  istante, righe storiche senza variante, referto, codici di uscita, JSON,
  distinzione fra riga del replay e click vero, partita con entrambe le specie
  (13 test), e la diagnosi delle partite scoperte con la sorgente fixture vera.
* **CI su dati veri** (`gh run watch`): run dry-run verde sull'intero periodo e
  sul solo periodo simmetrico; i numeri sopra arrivano dalle **annotazioni** del
  run, leggibili senza scaricare artifact.
* **Verifica dei due modelli sul Registro vero**: run `35570242579` (tag
  `verifica-modelli-upstash-2026-09-21`), `success`, sola lettura — i numeri di
  §4.4 sono le sue annotazioni (`[modelli]`, `[modelli-specie]`) e la causa
  delle 19 partite sta in `[diagnosi-riepilogo]` e `[diagnosi-parziale]`.
* **Fetch + diff**: i due comandi girano contro `origin/main` con la storia
  completa (gli snapshot vengono da git), e il referto dichiara il ref usato.

## 7. Cosa resta aperto

1. **Tetto di 100 kB del piano free JSONBin** → e' l'unica cosa che separa i due
   comandi dalla scrittura (punto §5) e riguarda anche la produzione: a ~74 kB su
   100 kB, i salvataggi dell'app si fermeranno fra ~38 righe. I secret ora
   funzionano (lettura remota OK): il blocco e' di capienza, non di credenziali.
2. Le partite solo-attuale (**9** offline/API nei dry-run, **19** sul Registro
   vivo al 21/09): dichiarate, spiegate, non forzate (§4.3 e §4.4). È l'unico
   punto che richiede una decisione: l'uguaglianza dei campioni esiste solo
   cambiando le regole del selettore, non il replay.
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
| `SoccerMath/registry_modelli_check.py` + `SoccerMath/test_registry_modelli_check.py` | la verifica dei due modelli sul Registro (sola lettura), 13 test |
| `.github/workflows/verifica_modelli.yml` | la verifica in CI (tag `verifica-modelli-*`): numeri e causa come annotazioni |
| `audit/test_diagnose_scarti.py` | la diagnosi delle partite scoperte, con la sorgente fixture vera (`api`) |
