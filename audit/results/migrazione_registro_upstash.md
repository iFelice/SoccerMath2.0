# Migrazione del Registro: da JSONBin a Upstash (referto)

Data: 2026-09-21 · Commits: `bcbb273` → `acfd645` (fase A→E) · Proposta e numeri
della scelta: `audit/results/proposta_shard_registro.md` §8–§9.

## 1. Perché (misurato, non stimato)

Il Registro era **un unico documento** riscritto per intero a ogni salvataggio.
Con JSONBin free questo significa un tetto di **100 kB per record**: il replay
del 20/09/2026 è stato **rifiutato con HTTP 403** («Free users cannot update a
record over 100kb») con un payload di **140353 B / 206 righe**. Il Registro live
era già a **108 righe / 52,2 kB**: ~150 righe per bin, cioè poche settimane di
margine, e ogni click dell'app rischiava di fallire per colpa di righe scritte
giorni prima.

## 2. La scelta

**Upstash Redis free via REST**: 256 MB, **500.000 comandi/mese**, 1 DB, nessuna
carta, `/multi-exec` atomico disponibile. Il Registro diventa un **hash**: *una
riga = un campo*, con chiave `dedup_key` (la stessa della fusione). Un salvataggio
tocca solo le righe nuove o cambiate, non riscrive lo storico.

JSONBin **resta l'archivio dichiarato**: 108 righe, non più scritto.

## 3. Le fasi, con gli esiti

| fase | cosa | esito misurato |
|---|---|---|
| A | `registry_store.py`: due backend dietro una facciata (`jsonbin` = comportamento di prima byte per byte; `upstash` = `HSET` per riga). App e replay passano da lì. | 885 test verdi |
| B | sola lettura dai runner (dove stanno i secret) | JSONBin **108** righe / 52,2 kB · Upstash **0** righe · confronto 108/0/0 · **nessuna scrittura** |
| C | copia: `HGETALL` + **un solo** `HSET` (108 righe, 56354 B), poi rilettura e confronto per chiave | **identici**: solo su JSONBin 0 · solo su Upstash 0 · diverse 0 |
| D | scrittura: finestra simmetrica, poi legacy | simmetrica **108 → 206** (98 aggiunte; payload 140354 B, *esattamente* quello che JSONBin rifiutava) · legacy **206 → 233** (27 aggiunte) · rilancio a Registro completo: **0 scritture, 0 sovrascritture** |
| E | istantanea giornaliera `sm:registro:snapshot:<giorno>` (1 `SET`), riletta e confrontata | **233 righe · 164243 B · fedele** (0/0/0) |

Comandi consumati dalla migrazione: **~40 su 500.000** (0,008%). In esercizio: un
salvataggio = 1 lettura + 1–2 `HSET`; l'istantanea = 3 comandi al giorno (0,02%
del mensile). Spazio: **233 righe = 160,4 kB su 256 MB** (0,06%).

## 4. Quattro cose scoperte misurando (nessuna ipotizzata)

1. **`HGETALL` risponde con un array piatto.** L'API REST di Upstash restituisce
   `["campo", "valore", ...]` (forma RESP2), non un oggetto JSON. La prima copia
   era *scritta bene* e «riletta» come vuota: 108 righe sulla chiave, «0 righe»
   in lettura. Ora `registry_store.hash_da_risposta()` accetta entrambe le forme
   e, su una risposta inattesa, **alza** l'errore invece di valere "vuoto" — su un
   percorso di scrittura "vuoto" vuol dire riscrivere tutto sopra lo storico.
2. **Rilanciare il replay a Registro completo usciva 1.** Le azioni sono un
   `Counter`: la chiave `aggiunta` non esiste se vale zero, e `None != 0` faceva
   sembrare fallita una scrittura che *non doveva* avvenire (idempotenza).
3. **Copertura e click-veri leggevano JSONBin** mentre il replay scriveva su
   Upstash: il referto descriveva 108 righe e la scrittura ne produceva 233.
   Ora `registry_coverage_check.load_registry_readonly()` passa dallo strato
   unico e dichiara la fonte (`upstash` / `jsonbin` / `file locale (motivo)`).
4. **In Streamlit Cloud i secret non stanno in `os.environ`.** Lo strato leggeva
   solo l'ambiente: il passaggio a Upstash in app non avrebbe avuto alcun effetto
   (backend JSONBin, credenziali «non configurate») fino al primo salvataggio
   rifiutato. Ora `config._get_secret` copre anche `st.secrets`.

Bug veri trovati *dai test* durante la fase A/C: la copia usava il **conteggio**
del piano al posto delle **righe** (`TypeError: 'int' object is not iterable`).

## 5. Stato del Registro dopo la migrazione

| dove | righe | dimensione | ruolo |
|---|---|---|---|
| hash Upstash `sm:registro` | **233** | 160,4 kB | **Registro vivo** (app e replay scrivono qui) |
| `sm:registro:snapshot:2026-09-20` | 233 | 164243 B | punto di ripristino giornaliero |
| bin JSONBin | 108 | 52,2 kB | **archivio dichiarato**, non più scritto |
| file locale dell'app | — | — | copia dell'app, usata solo se il remoto non risponde |

## 6. Comandi (il comando sta nel nome del tag)

| tag | cosa fa | scrive? |
|---|---|---|
| `migra-registro-prova-*` | dice cosa copierebbe | no |
| `migra-registro-esegui-*` | copia + verifica di uguaglianza | sì (solo righe assenti) |
| `migra-registro-diagnostica-*` | prova di andata e ritorno su una chiave a parte | 1 campo, poi lo rimuove |
| `istantanea-registro-*` | istantanea del giorno, riletta e confrontata | sì (1 chiave) |
| `replay-write-{sym,legacy}-upstash-*` | replay che scrive sul Registro vivo | sì (solo righe nuove) |
| `replay-check-{sym,legacy}-*` | stessa finestra in sola lettura | no |

## 7. Cosa resta a mano (una volta)

- **Streamlit Cloud → Secrets**: `REGISTRY_BACKEND = "upstash"` ✅ fatto il
  2026-09-21. Servono anche `UPSTASH_REDIS_REST_URL` e
  `UPSTASH_REDIS_REST_TOKEN` (già presenti).
- **GitHub**: i secret `UPSTASH_*` sono già presenti per i runner. La variabile
  di repository `REGISTRY_BACKEND` è **opzionale**: senza, la CI usa l'hash
  (default del workflow) e il tag `-jsonbin-` serve a leggere l'archivio.
- **Istantanea automatica**: il `cron` di GitHub gira solo dai workflow del
  branch di default, quindi diventa attivo quando questo lavoro arriva su `main`.
  Fino ad allora l'istantanea si comanda col tag.
