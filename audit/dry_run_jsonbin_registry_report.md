# Dry-run migrazione Registro Predizioni — JSONBin (registro REALE)

**Data esecuzione:** 2026-09-05
**Branch:** `arena/01a07126-soccermath2-0`
**Base:** `origin/main` @ `445c3af9fc8b0598e77ce0c63c5b32287cd0cf24`

> **ESITO: il dry-run sul registro REALE JSONBin NON è stato eseguibile in questa
> sessione.** Due blocchi ambientali lo impediscono (§2). Nessun dato remoto è
> stato letto né modificato. Il report documenta cosa è stato verificato, cosa
> resta da eseguire e il comando esatto da lanciare in un ambiente con accesso.

---

## 1. Configurazione JSONBin realmente usata dall'app

`SoccerMath/app.py` → `load_predictions()` (righe 164-181) usa il **remoto come
fonte primaria** e il file locale solo in fallback:

```python
if JSONBIN_API_KEY and JSONBIN_BIN_ID:
    r = requests.get(f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}/latest",
                     headers={"X-Master-Key": JSONBIN_API_KEY}, timeout=5)
    ...
if os.path.exists(PREDICTIONS_FILE):   # fallback locale
```

| Elemento | Valore |
|---|---|
| Endpoint lettura | `https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}/latest` |
| Endpoint scrittura | `https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}` (PUT) |
| Header auth | `X-Master-Key: {JSONBIN_API_KEY}` |
| Credenziali | `config.py::_get_secret()` → env var → `SoccerMath/.env` → `st.secrets` |
| Fallback locale | `SoccerMath/database/predictions.json` (git-ignored) |

Il bin ID **non è hardcoded** in nessun punto del repository: è esclusivamente
un segreto di deploy. Verificato su tutta la storia Git (363 commit): nessun
bin ID o master key è mai stato committato.

## 2. Perché il dry-run reale non è stato eseguibile

### Blocco A — credenziali assenti

```
JSONBIN_API_KEY set: False
JSONBIN_BIN_ID  set: False
local predictions.json exists: False
```

Nessuna delle tre fonti (env, `.env`, `st.secrets`) è popolata nel sandbox, e
i GitHub Actions secrets non sono leggibili (`HTTP 403`). Senza bin ID **non
esiste alcun indirizzo da interrogare**.

### Blocco B — egress di rete filtrato

```
https://pypi.org/simple/    -> HTTP 200
https://api.jsonbin.io/...  -> SSLError (TLS EOF)
https://api.github.com      -> SSLError (TLS EOF)
```

Il sandbox risolve il DNS ma il proxy TLS chiude le connessioni verso domini
fuori allowlist. Anche con le credenziali, la GET verso JSONBin fallirebbe.

**Conseguenza:** i numeri richiesti (totale entry, conteggi per categoria,
intervallo temporale, elenco Legacy→Pre-fix) **si possono produrre solo da un
ambiente con credenziali e accesso a `api.jsonbin.io`**. Qualunque cifra
riportata qui come "registro reale" sarebbe inventata.

## 3. Cutoff utilizzato e verifica Git

Il cutoff è definito in `SoccerMath/prediction_registry.py` ed è stato
**verificato contro la storia Git reale** (non è inventato):

| Ruolo | Commit | Timestamp autore (UTC) | In `main`? |
|---|---|---|---|
| Commit del fix | `ae8784d643575593f77241c54a1930e7bd48145f` | `2026-09-04 15:40:10` | ✅ sì |
| Merge in `main` | `dc192d5eaa36968380f8bde823ca1abe9792e65d` | `2026-09-04 16:50:17` | ✅ sì |

Messaggio del commit di fix:
`fix(top-mix): elimina NG ~99.8% causato da lambda ~0 per neopromosse senza dati`

Regola di classificazione (stagione target `2026/2027`):

- `salvato_il` **<** `2026-09-04 15:40:10 UTC` → **`pre_shrinkage`**
- `salvato_il` nella finestra tra i due commit → **`ambiguous`**
- `salvato_il` **≥** `2026-09-04 16:50:17 UTC` senza `model_version` → **`ambiguous`** (mai promosso a post)
- altre stagioni → **`legacy`**
- `model_version == post_shrinkage_v1` → **`post_shrinkage_v1`**

Il clone era *shallow* (`depth=1`) e i commit del cutoff non erano
verificabili; è stato eseguito `git fetch --unshallow` per validarli.

## 4. Dry-run di riferimento sullo snapshot Git

Non essendo raggiungibile il remoto, il dry-run è stato eseguito **in sola
lettura** sull'ultimo `predictions.json` mai committato
(`5df4a3a`, poi cancellato in `0b64383`), estratto in `/tmp` senza toccare il
working tree.

```
python audit/tag_pre_shrinkage_predictions.py --source /tmp/pred_snapshot_5df4a3a.json
```

| Metrica | Valore |
|---|---|
| Totale entry | **56** |
| di cui stagione 2026/2027 | **27** |
| `pre_shrinkage` (dopo migrazione) | **27** |
| `legacy` | **29** (tutte 2025/2026) |
| `post_shrinkage_v1` | **0** |
| `ambiguous` | **0** |
| Intervallo entry pre-fix | `2026-08-17 16:28` → `2026-08-26 09:31` UTC |
| Record senza `salvato_il` | 0 |

⚠️ Questo snapshot è di **agosto 2026** e **non contiene** i due pronostici
NG 99.8% del 5 settembre: non è il registro reale, serve solo a validare la
meccanica dello script.

## 5. Verifica dei due pronostici NG 99.8%

Non essendo presenti nello snapshot, la verifica è stata condotta con un
**mock JSONBin locale** contenente i due pronostici più due controlli
progettati per isolare la variabile "probabilità":

| Entry | prob | `salvato_il` (UTC) | Esito atteso | Esito ottenuto |
|---|---|---|---|---|
| Man City – Coventry City, NG | 99.8% | `2026-09-04 15:35` (pre) | pre-fix | ✅ `to_tag_pre_shrinkage` |
| Hull City – Aston Villa, NG | 99.8% | `2026-09-04 15:35` (pre) | pre-fix | ✅ `to_tag_pre_shrinkage` |
| **Controllo A** — stessa prob, salvato dopo il merge | 99.8% | `2026-09-05 08:00` (post) | **non** pre-fix | ✅ `ambiguous`, `will_tag=False` |
| **Controllo B** — prob bassa, salvato prima del fix | 52.0% | `2026-08-29 09:00` (pre) | pre-fix | ✅ `to_tag_pre_shrinkage` |

**Conclusione:** il Controllo A (99.8% ma **non** taggato) e il Controllo B
(52% **sì** taggato) dimostrano che il tag dipende esclusivamente da
**stagione + `salvato_il` + `model_version`**, e **mai** dalla probabilità.

Verifica strutturale a supporto: un'analisi AST di `classify_entry`,
`should_tag_pre_fix`, `entry_era_by_time`, `entry_generation_time` e
`season_from_entry` mostra che le uniche chiavi di record lette sono
`model_version`, `stagione`, `data`, `salvato_il`. I campi `prob_sicuro`,
`pronostico_sicuro`, `esito`, `risultato_reale`, `top3`, `mercato_standard`
**non sono mai letti** dalla catena di classificazione.

## 6. Sicurezza — backup completo prima di qualsiasi scrittura

Requisito: *"prima di qualsiasi futura scrittura verifica che sia possibile
creare un backup completo del JSONBin"*.

Nel codice originale il backup copriva **solo il file locale**:

```python
backup = backup_prediction_file(output) if output.exists() else None
write_predictions_file(output, migrated_records)
if push_remote:
    requests.put(...)      # ← PUT sul bin senza alcun backup del remoto
```

Poiché `predictions.json` **non esiste**, `output.exists()` è `False` →
`backup = None` → `--apply --push-remote` avrebbe **sovrascritto il bin remoto
senza alcun punto di ripristino**. Corretto (§7): la PUT ora è preceduta da un
backup integrale del bin e **aborta** se il backup fallisce.

Preflight non distruttivo (**sola GET**, nessuna scrittura remota):

```
python audit/tag_pre_shrinkage_predictions.py --verify-backup
```

Validato contro il mock: `[BACKUP][OK] ... (5 entry)`, exit `0`; senza
credenziali esce `2` con `[BACKUP][KO]`. Il backup è scritto in
`SoccerMath/database/predictions_jsonbin_<timestamp>.json.bak`, già coperto da
`.gitignore` (`database/*.json.bak`).

**Nell'ambiente attuale il backup completo NON è realizzabile** (blocchi A+B):
di conseguenza **nessuna scrittura deve essere tentata da qui**.

## 7. Correzioni allo script (`audit/tag_pre_shrinkage_predictions.py`)

| # | Problema | Correzione |
|---|---|---|
| 1 | **Scrittura remota senza backup** — `--push-remote` faceva PUT sul bin senza copia di sicurezza quando il file locale non esiste | `backup_remote_registry()` scarica e salva il bin **prima** della PUT; se fallisce, la PUT non parte. Errore HTTP → eccezione con percorso del backup |
| 2 | **Fallimento silenzioso** — se la GET falliva, lo script stampava `TOTALE entry: 0`, indistinguibile da un registro realmente vuoto | La lettura remota solleva `RuntimeError` con causa esplicita; `--remote` esce con codice `2` invece di produrre un report fuorviante |
| 3 | **Impossibile forzare il remoto** — il file locale aveva sempre la precedenza, al contrario di `app.load_predictions()` | Nuovo `--remote`: legge il registro reale ignorando il locale, replicando la precedenza dell'app |
| 4 | **Report incompleto** — mancavano conteggio stagione 2026/27, intervallo delle sole entry pre-fix ed elenco Legacy→Pre-fix | Report esteso con tutte le voci richieste, incluso l'elenco dettagliato delle predizioni che cambierebbero etichetta |
| 5 | **`NameError` latente** — `datetime` usato in annotazione senza import (dormiente grazie a `from __future__ import annotations`) | Aggiunto `from datetime import datetime` |
| 6 | Cutoff dichiarato ma non verificato | Il report ora confronta i due commit con `git show` e segnala `[OK]` / `[MISMATCH]` / non verificabile |

Nuovi flag: `--remote`, `--verify-backup`, `--backup-path`, `--explain-match`.
La **logica di classificazione non è stata toccata**: sullo snapshot i conteggi
sono identici prima e dopo (27 / 29 / 0 / 0).

**Regressione:** 37/37 test OK
(`audit.test_prediction_registry`, `audit.test_prediction_registry_date_sorting`).

## 8. Prova di assenza di scritture

Il mock JSONBin ha registrato **ogni** richiesta ricevuta durante l'intera
sessione (dry-run + preflight backup):

```
GET /v3/b/mockbin123/latest
GET /v3/b/mockbin123/latest
GET /v3/b/mockbin123/latest
GET /v3/b/mockbin123/latest
---
4 GET · 0 PUT · 0 POST · 0 PATCH
```

- ❌ Nessun `--apply` eseguito
- ❌ Nessun PUT/POST/PATCH verso JSONBin (né reale né mock)
- ❌ Nessun `predictions.json` creato o ripristinato nel working tree
- ❌ Nessuna modifica a risultati, probabilità, esiti, date o altri campi

## 9. Comando da eseguire in ambiente autorizzato

```bash
export JSONBIN_API_KEY='<master key>'
export JSONBIN_BIN_ID='<bin id>'

# 1. Dry-run sul registro REALE (sola lettura)
python audit/tag_pre_shrinkage_predictions.py --remote

# 2. Verifica esplicita dei due pronostici NG 99.8%
python audit/tag_pre_shrinkage_predictions.py --remote --explain-match "Coventry"
python audit/tag_pre_shrinkage_predictions.py --remote --explain-match "Hull"

# 3. Preflight backup — deve stampare [BACKUP][OK] prima di ogni scrittura
python audit/tag_pre_shrinkage_predictions.py --verify-backup
```

Solo dopo che i passi 1-3 sono stati rivisti si potrà valutare la migrazione.
`--apply` da solo scrive **esclusivamente** il file locale; il bin remoto
richiede in aggiunta `--push-remote`, ora subordinato al backup integrale.
