# Proposta: ripartire il Registro su più bin (piano free JSONBin)

**Stato**: proposta da approvare, nessuna riga di codice toccata finora.
**Perché**: il PUT del replay è stato respinto con
`HTTP 403 Free users cannot update a record over 100kb` — payload **140.353 byte**
per 206 righe. Il limite non e' del replay: e' il tetto del **piano free**
(100 kB per record, [pricing ufficiale](https://jsonbin.io/pricing), 10.000
richieste una tantum), e il Registro e' **una sola** record JSON riscritta per
intero a ogni salvataggio.

## 1. Le misure che decidono il progetto

| misura | valore | fonte |
|---|---|---|
| payload respinto | 140.353 B per 206 righe | risposta del servizio, run `replay-write-sym-2026-09-20` |
| costo medio per riga (registro misto live+replay) | **~681 B** | 140.353 / 206 |
| costo medio per riga (righe ricostruite, campo ricco) | **~885 B** | copia fusa offline, 113,3 kB / 131 righe |
| Registro live oggi | **108 righe ≈ 74 kB** | `fonte: jsonbin, righe_prima: 108` |
| tetto del piano free | **100 kB** | pricing |
| spazio residuo per i salvataggi dell'app | **~26 kB ≈ 38 righe** | 100 − 74 |
| ritmo osservato: replay (30/08 → 20/09) | 131 righe / 22 giorni = **6,0 righe/giorno** | copia fusa |
| ritmo osservato: app (dall'inizio stagione) | 108 righe / 36 giorni = **3,0 righe/giorno** | Registro live |

**Proiezione** (al ritmo osservato, 9 righe/giorno fra app e replay):

| orizzonte | righe | un bin unico | mese intero | mese × variante |
|---|---|---|---|---|
| una giornata | ~9 | 6 kB ✅ | — | — |
| un mese | ~179 | **119 kB ❌** | **119 kB ❌** | ~61-78 kB ✅ |
| una stagione | ~2.100 | **~1,4 MB ❌❌** | — | — |

Conclusione: **"una stagione per bin" non basta, "un mese per bin" non basta.**
La chiave di frazionamento deve scendere a **stagione × mese × variante**, che
al ritmo osservato resta sotto i 100 kB con margine (~20-40%).

## 2. Progetto

### 2.1 Nomi e manifest

* **Shard dati**: nome deterministico, ricavabile dai dati senza indovinare:
  `sm-registry-<stagione>-<aaaa-mm>-<variante>`, es. `sm-registry-2026-27-2026-09-current`.
  Deterministico = si puo' ricalcolare l'elenco anche se il manifest si perde.
* **Manifest**: un bin piccolo (`sm-registry-manifest`) con
  `{"schema": 1, "shards": [{"nome", "bin_id", "stagione", "mese", "variante",
  "righe", "byte", "aggiornato_il"}], "archivio": {"bin_id", "righe", "nota"}}`.
  Contiene solo metadati: poche centinaia di byte, riscritto a ogni salvataggio.
* **Archivio**: il bin **attuale** resta intatto e leggibile, dichiarato nel
  manifest come `archivio`. Non viene mai riscritto: e' la rete di sicurezza e
  la fonte storica (requisito "mai sovrascrivere" rispettato anche in migrazione).

### 2.2 Lettura (unione, con dedup)

`load_predictions()` diventa: `manifest` → GET dei soli shard rilevanti →
unione → dedup per `dedup_key` (idempotente: se durante la migrazione una riga
sta in due posti, vince **una** copia; l'ordine e' dichiarato: archivio prima,
shard dopo, cosi' la copia piu' recente vince).

* Per le viste della stagione corrente: manifest + shard della stagione corrente
  (~9 mesi × 2 varianti = 18 GET, una volta per TTL di cache: l'app ha gia'
  `st.cache_data(ttl=1800)`).
* Per l'archivio storico: shard degli anni precedenti + bin archivio, caricati
  su richiesta (non a ogni rerun).
* Se il manifest non e' raggiungibile: si legge il bin archivio e **si dichiara**
  la modalita' degradata (niente numeri inventati, e' la stessa regola gia' in
  vigore per il Registro letto in modo stretto).

### 2.3 Scrittura (solo gli shard toccati)

`upsert` + salvataggio: si partiziona il risultato per chiave di shard e si
**PUT solo gli shard il cui contenuto e' cambiato** (una manciata di kB), poi il
manifest. Ordine: **prima i dati, poi il manifest** — se il manifest non si
aggiorna, lo shard resta "orfano" ma i dati non si perdono, e la scrittura e'
idempotente al giro dopo (stessa proprieta' di `upsert_prediction_entry`).

* Nessun cambiamento ai campi delle righe: struttura identica, nessuna etichetta
  (vincolo di commessa).
* Nessuna cancellazione: gli shard crescono per aggiunta; un aggiornamento di
  esito riscrive la stessa riga nella stessa posizione logica.
* Guardia di capienza: se la fusione di uno shard supera **85 kB**, la scrittura
  si **rifiuta** con un errore che dice quale shard e perche', invece di farsi
  respingere dal servizio a meta' (e la via d'uscita e' dichiarata: dimezzare il
  mese, es. `2026-09-a` / `2026-09-b`).

### 2.4 Perche' non altre strade

* **Solo `model_variant`**: raddoppia la capacita' una volta, non risolve la
  crescita (una stagione resta ~700 kB per variante).
* **Solo per stagione**: la stagione corrente da sola supera il tetto (tabella §1).
* **Comprimere/asciugare le righe**: vietato dal vincolo "struttura identica".
* **Scrivere a tranche nel bin unico**: sposta il problema di qualche riga e
  blocca i salvataggi dell'app prima; e' la strada peggiore.

## 3. Migrazione (mai distruttiva, a fasi verificabili)

| fase | cosa succede | verifica | rollback |
|---|---|---|---|
| **A** | strato `registry_store.py` con le funzioni di chiave/unione/partizione + test, **flag `REGISTRY_SHARDS=off`** (comportamento attuale) | suite completa verde, nessuna scrittura | niente da annullare |
| **B** | in CI, **sola lettura**: legge il bin attuale, calcola la partizione e produce un referto (shard, righe, byte attesi) senza scrivere | referto: somma righe = righe lette, nessuna riga persa | nessuna scrittura |
| **C** | creazione shard + copia, **archivio intatto**; lettura commutata all'unione (flag on) con confronto "unione == bin storico" riga per riga | test di equivalenza sull'insieme delle chiavi | flag off: si torna al bin unico |
| **D** | scrittura commutata ai shard; i due tag di scrittura del replay completano le due finestre | copertura finale + conteggi di fusione per shard | flag off + il bin archivio e' ancora la verita' |
| **E** | dopo una settimana di uso reale senza anomalie: il bin storico resta archivio dichiarato, il manifest e' la fonte primaria | copertura per modello sul Registro unito | — |

## 4. Test da scrivere (prima del codice, come sempre in questa commessa)

1. **Chiave stabile**: stessa riga → stesso shard, anche fra esecuzioni e
   processi diversi; righe senza `kickoff_utc` ricadono sulla data italiana.
2. **Partizione completa**: l'unione degli shard contiene **esattamente** le
   righe di partenza (nessuna persa, nessuna duplicata) — il test che conta.
3. **Unione con dedup**: una riga presente in archivio **e** in uno shard compare
   una volta sola; la copia dello shard vince.
4. **Scrittura solo degli shard toccati**: aggiungere una riga di settembre non
   tocca lo shard di agosto (verificato sui PUT simulati, non a occhio).
5. **Manifest dichiara il vero**: righe e byte nel manifest corrispondono a
   quanto scritto; un manifest disallineato si corregge al giro dopo.
6. **Guardia di capienza**: shard oltre 85 kB → rifiuto con messaggio che nomina
   lo shard (nessun silenzio, nessun troncamento).
7. **Degrado dichiarato**: manifest irraggiungibile → si legge l'archivio e la
   fonte dice "archivio (manifest non raggiungibile)".
8. **Flag off = identico a oggi**: con `REGISTRY_SHARDS=off` il comportamento e'
   byte per byte quello attuale (test di regressione).
9. **Replay**: `merge_entries` invariato; il passo di scrittura fa N PUT e
   riporta per shard righe e byte; la copertura legge l'unione.

## 5. Costi e richieste (piano free: 10.000 richieste)

* Lettura app: 1 GET manifest + ~18 GET shard della stagione, **con cache 30'**:
  ~20 richieste per finestra di cache (contro 1 di oggi).
* Scrittura: ~2-3 PUT (shard toccati + manifest) invece di 1.
* Replay: la scrittura completa delle due finestre tocca ~4 shard (ago/set × 2
  varianti) + manifest ≈ 5 PUT.
* Con 10.000 richieste il margine resta ampio; se il consumo diventasse un
  problema, la prima leva e' la cache di lettura (gia' prevista), non la
  riduzione dei dati.

## 6. Cosa NON cambia

* Contenuto delle righe: identico, nessun campo nuovo, nessuna etichetta.
* Soglie e selettore: 0,55 1X2 / 0,60 Totali e veto invariati.
* `dedup_key`: invariato; nessuna riga esistente sovrascritta.
* I due comandi del replay e i loro tag: invariati dall'esterno.

## 7. Domande aperte per te

1. **Granularita'**: confermi `stagione × mese × variante` (con la via d'uscita
   dei mesi dimezzati), o preferisci partire da `stagione × mese` e dimezzare
   solo quando serve?
2. **Bin**: li crei tu su JSONBin (io non ho accesso al tuo account) o vuoi che
   la CI li crei automaticamente via API quando manca lo shard? La seconda e'
   piu' comoda ma la CI deve poter creare record.
3. **Archivio storico**: il bin attuale resta un archivio dichiarato in sola
   lettura (consigliato), o vuoi che i suoi dati vengano spostati del tutto nei
   nuovi shard e il bin vecchio svuotato?

---

# 8. Alternative al frazionamento: quali servizi risolvono davvero (verificate)

Domanda posta: **npoint.io** puo' superare il problema del bin?

## 8.1 npoint.io: no, e per tre motivi indipendenti

1. **E' un archivio a senso unico, per progetto.** Dalla pagina ufficiale:
   *"n:point is a one-way JSON store: edit online, fetch via GET requests over
   API. Editing data over the API via POST requests is in private beta. Even
   once released, n:point is not meant to be a full backend for your app."*
   Il nostro Registro deve essere **scritto dall'app** a ogni click Top Mix (e
   dalla CI per il replay): senza scrittura via API non puo' fare da Registro.
2. **La scrittura via API e' riservata.** Nel codice del progetto gli
   aggiornamenti programmatici richiedono autenticazione **e** ``is_premium``; il
   wrapper Node piu' diffuso apre con: *"npoint.io is not giving out API keys to
   new users anymore. So if you don't own a legacy account then you cannot use
   this wrapper."* Per un account nuovo, di fatto, non c'e' scrittura.
3. **La lettura e' in cache CDN per 1 ora** (dalla documentazione del progetto:
   *1-hour Cloudflare cache on API responses*). Il nostro flusso e'
   leggi -> aggiungi -> scrivi: una lettura stantia = righe perse al salvataggio.
   Sarebbe un difetto **peggiore** del tetto di dimensione, perche' silenzioso.

In piu': limiti 100 richieste/min per IP e 600/min per bin, nessun limite di
dimensione documentato, nessun SLA, posizionamento esplicito "non per la
produzione".

**Verdetto**: npoint.io risolverebbe il problema di dimensione sostituendolo con
un problema di scrittura. Non e' utilizzabile come Registro.

## 8.2 Cosa servirebbe per NON frazionare: un tetto per record piu' alto

| servizio | tetto per record | scrittura via API | piano gratuito | verdetto per noi |
|---|---|---|---|---|
| **JSONBin** (oggi) | 100 kB free; Pro: **1 MB** secondo l'errore dell'API, **10 MB** secondo la tabella di prezzo (da verificare prima di pagare) | PUT | 10.000 richieste | serve il frazionamento: una stagione e' ~1,4-1,9 MB |
| **npoint.io** | non documentato | **no** (POST in private beta, premium/legacy) | rate limit | **scartato** (§8.1) |
| **Cloudflare KV** | **25 MiB per valore** | PUT via REST (senza Worker) | 1 GB, 100k letture/giorno, **1.000 scritture/giorno**, 1 scrittura/s per chiave | **elimina il frazionamento**: una chiave per stagione (~1,5 MB) sta largamente |
| **GitHub Contents API** | 100 MB per file | PUT (crea un commit) | 5.000 richieste/ora | gratis e **versionato** (ogni modifica del Registro e' un diff); ma mette i dati in commit sul repo |
| **Supabase** | Postgres, scrittura **per riga** | REST | 500 MB DB, 2 progetti | il modello giusto (niente riscrittura totale), ma i progetti free **vanno in pausa dopo 7 giorni di inattivita'** |
| **Cloudflare D1** | SQL, righe | REST/SQL | 5 GB, 5M letture righe/giorno | il piu' solido a lungo termine, il piu' lavoro da fare |

Due conseguenze da tenere presenti:

* **Anche jsonbin Pro non basta per una stagione intera** (1 MB per record
  secondo l'errore dell'API): pagare il piano Pro non eliminerebbe il
  frazionamento, lo rimanderebbe soltanto. Solo KV (25 MiB) o un database a
  righe lo eliminano davvero.
* **Chi risolve alla radice e' un archivio a righe**: il difetto di fondo non e'
  il tetto, e' che il Registro e' **un'unica record riscritta per intero** a ogni
  salvataggio (per questo un click dell'app puo' fallire per colpa di righe
  scritte giorni prima). KV con una chiave per stagione riduce il problema a
  "riscrivi una stagione", che con 25 MiB non e' piu' un vincolo pratico.

## 8.3 Le due strade, con il lavoro che comportano

| | **A. Frazionare su JSONBin** (proposta §1-7) | **B. Passare a Cloudflare KV** |
|---|---|---|
| servizio nuovo | no | account Cloudflare + namespace + API token |
| codice nuovo | chiave di shard, manifest, unione con dedup, guardia di capacita' | client REST KV (GET/PUT), una chiave per stagione: **meno** logica del frazionamento |
| codice da toccare | `prediction_registry`/`app` (lettura e scrittura) | gli stessi punti |
| migrazione | copia per shard, archivio intatto | copia della stagione in una chiave, bin JSONBin come archivio |
| rischio nuovo | nessuno (stesso servizio) | coerenza "eventually consistent" (~secondi) e nessun confronto-e-scambia atomico: con **un solo scrittore alla volta** (click o CI) il rischio pratico e' basso, ma va dichiarato |
| costi | 0 (piano free) | 0 (1.000 scritture/giorno sono ~100 volte il nostro uso) |

Consiglio, in una riga: **se si vuole restare su JSONBin, la strada A e' quella
descritta sopra; se si accetta un servizio nuovo, la B fa meno codice e toglie il
tetto (25 MiB)**, al prezzo di un vincolo di coerenza da dichiarare. npoint.io
non e' una terza opzione.

## 8.4 Cosa non cambia in nessuna delle due

Contenuto delle righe, soglie (0,55 1X2 / 0,60 Totali), veto, `dedup_key`,
nessuna sovrascrittura, i due comandi del replay e i loro tag. Cambia solo **dove**
finiscono le righe.
