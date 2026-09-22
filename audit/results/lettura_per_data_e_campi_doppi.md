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
4. **Correzione di questa nota**: `dedup_key` (la chiave della fusione e il nome
   del campo) legge la variante **per data**, non col default: e' proprio cosi'
   che il replay ha potuto aggiungere le 20 righe. Il default fisso resta solo in
   `model_variant_of`, cioe' sul **valore** del campo che l'app scrive per un
   click nuovo (e sugli id). Una partita con una riga di un `selector_version`
   diverso resta, per progetto, una riga distinta: non e' un difetto, e' la
   regola di dedup dichiarata.

## Esito finale (misurato, run del 2026-09-21)

| run | comando | esito |
|---|---|---|
| `35583044605` | verifica dei due modelli (sola lettura) | **verde**: `Registro (upstash): 233 righe totali`, gate «tutte le 10 partite senza riga ATTUALE hanno una causa MISURATA» |
| `35583046959` | check del replay (sola lettura) | **verde**: `righe_prima 233 → righe_dopo 233`, `azioni: {"gia_presente": 112}`, **`aggiunta 0`** |

I conti tornano **esattamente**:

```
righe senza campo variante (logiche): 108  (tutte nate prima del merge: 46 nella
                                            finestra ricostruibile + 62 prima)
  di cui 20 "cedono" il campo alla riga attuale che il replay ha scritto
        → la riga vecchia resta sotto il nome nuovo: 1 copia
  di cui 88 riscritte sotto il nome nuovo col nome vecchio ancora presente: 2 copie
campi totali = 233 righe + 88 doppioni = 321
variante letta sui campi   : current 77 · legacy 244 (= 156 + 88)
variante letta sulle righe : current 77 · legacy 156        (77 + 156 = 233)
```

Registro vivo: **233 righe · 160,4 kB** su Upstash (tetto 256 MB) · snapshot
`sm:registro:snapshot:2026-09-20` (233 righe · 164243 B) · archivio JSONBin 108
righe, **0 solo su JSONBin · 0 contenuto diverso**.

Modello attuale: **57 → 77 partite coperte**; le partite senza la riga attuale
passano da **30 a 10**, tutte e 10 con causa misurata (sotto soglia o veto) e
**0 chiavi attuali occupate**.
