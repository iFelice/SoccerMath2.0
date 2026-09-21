# Lettura della variante per data: effetto sui campi dell'hash (misurato)

Data: 2026-09-21 · ramo `arena/01a0bf2d-soccermath2-0`

## Cosa era in discussione

La variante di una riga **senza** `model_variant` non si legge col default fisso
(`current`): si legge dalla **data**. Una riga nata prima del merge di PR#24
(`2026-09-18T21:51:58Z`) e' del motore che girava allora, cioe' `legacy`.
La correzione e' in `prediction_registry.model_variant_read` (+ `entry_instant`,
`model_variant_read_source`) ed e' usata da `registry_coverage`,
`registry_modelli_check`, `audit/diagnose_scarti_model_variant.py`, `app.py`.
`model_variant_of` (percorso di scrittura e id) resta quello di prima: chiavi e
id non cambiano.

## Effetto collaterale che questa correzione ha prodotto (misurato, non dedotto)

Il **nome del campo** dell'hash Upstash e' `field_of(riga)` = `dedup_key(riga)`,
e la variante fa parte della chiave. Cambiando la convenzione di **lettura**,
il nome che una riga senza campo **ricalcola** adesso non e' piu' quello con cui
era stata scritta: la riga resta sotto il nome vecchio **e** viene riscritta
sotto quello nuovo.

Misura (run di sola lettura `35580278105`, commit `4aaf793`):

```
- campi dell'hash: 321 · allineati alla chiave ricalcolata 233 ·
  con nome vecchio 88 · righe distinte 233 · chiavi doppie 88
- doppioni: 88 righe scritte due volte (stesso contenuto) ·
  0 chiavi con valori DIVERSI
- variante letta sui CAMPI (campo esplicito o DATA): current 77, legacy 244
- righe senza campo variante: 196 (valori; la riga per chiave e' misurata al giro successivo)
- Upstash: 321 righe · 195.9 kB · chiavi nel database (2): sm:registro, sm:registro:snapshot:2026-09-20
- confronto con l'archivio JSONBin: solo su JSONBin 0 · contenuto diverso 0
```

Lettura dei numeri:

* **321 = 233 + 88**: i campi sono 321, le righe logiche 233; gli 88 doppioni
  sono **la stessa riga due volte** (nome vecchio + nome nuovo). Nessun campo
  con contenuto diverso sotto la stessa chiave: **nessuna riga sostituita**.
* La doppia scrittura e' un effetto **una volta sola**: la riga riscritta porta
  il nome che ricalcola, quindi il salvataggio successivo la salta (verificato
  dal codice del salvataggio: salta le coppie campo/valore identiche).
* L'archivio JSONBin resta allineato: **0 righe solo su JSONBin, 0 con
  contenuto diverso**. Le copie di sicurezza sono la chiave
  `sm:registro:snapshot:2026-09-20` e l'archivio JSONBin (108 righe).

## Cosa e' stato fatto (commit locali, non ancora su GitHub)

* `registry_store.upstash_rows`: legge **una riga per chiave logica** (preferendo
  il campo allineato alla chiave ricalcolata). Se due campi portano la stessa
  chiave con contenuto **diverso** non si sceglie in silenzio:
  `RegistryStoreError`. Motivo: contare due volte gonfia righe del periodo, kB e
  copertura.
* `registry_backend_status`: distingue **doppioni identici** (disordine) da
  **chiavi con valori diversi** (da guardare, con le due righe stampate) e conta
  la variante letta **sui campi** e **sulle righe**; righe senza campo.
* Test: 2 nuovi sull'hash doppio (stessa riga → una sola lettura; contenuti
  diversi → errore) e 2 sul referto; i test dei comandi di rete verificano che
  resti **sola lettura** (`HGETALL`, `HGETALL`, `DBSIZE`, `KEYS`).
* Suite completa: **927 passed**, 1006 subtests, 87.9 s.

## Resta da fare (bloccato: GitHub non autentica piu')

1. **Push** dei 3 commit locali (`290f83c`, `5679a35`, `3456685`) e aggiornamento
   della PR #28.
2. **Due run di sola lettura** per chiudere i conti con la lettura a una riga per
   chiave: la check del replay (`aggiunta` attesa 0, righe del periodo) e la
   verifica dei due modelli (gate + conteggi per variante sulle righe logiche).
3. **Decisione dell'utente** sugli 88 campi con nome vecchio: sono righe identiche
   sotto un nome che non si usa piu'. Lasciarli non cambia nulla (la lettura li
   ignora); toglierli sarebbe una **cancellazione** e non si fa senza un tuo via
   libera. L'archivio JSONBin e lo snapshot sono intatti in ogni caso.
4. Il punto aperto dichiarato, **non** risolto: il percorso di **scrittura**
   (`dedup_key`) legge ancora la variante col default per gli id. Conseguenza:
   se il replay rilanciasse la finestra vecchia, per una partita che ha gia' un
   click vero potrebbe aggiungere una riga `legacy` del replay (chiavi diverse).
   Non e' stato toccato di proposito: cambiare la scrittura non era chiesto e
   avrebbe richiesto il tuo via libera.
