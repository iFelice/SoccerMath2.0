# Registro Predizioni & Tracking — versione motore e separazione pre/post-fix

Report della migrazione per il fix di shrinkage/lambda-zero (PRIOR_MATCHES=6).
**La migrazione non è stata applicata: solo dry-run.**

## 1. Stato del registro reale analizzato

- File locale previsto: `SoccerMath/database/predictions.json`
  (definito da `config.PREDICTIONS_FILE`).
- Formato persistito: `{"data": [...]}`.
- Struttura entry:
  `match_id`, `home`, `away`, `campionato`, `giornata`, `data`,
  `pronostico_sicuro`, `mercato_standard`, `top3`, `prob_sicuro`,
  `risultati_attesi`, `risultato_reale`, `esito`, `tipo`, `stagione`,
  `salvato_il`.
- `salvato_il`: timestamp locale `Europe/Rome`, formato `dd/mm/YYYY HH:MM`.
- `stagione`: è esplicito solo nei record più recenti; per i legacy viene
  derivato dalla data partita (`data`).
- Sincronizzazione JSONBin: `load_predictions()` legge prima il remoto
  (se `JSONBIN_API_KEY` e `JSONBIN_BIN_ID` sono configurati) poi il file
  locale; `save_predictions()` ora scrive **prima** il file locale (con
  backup) e **dopo** il remoto.

### Dato davvero disponibile nel sandbox

Nel working tree **non esiste** `predictions.json` e **non sono configurate**
credenziali JSONBin nell'ambiente locale. Il dry-run sul registro reale
disponibile quindi vede **0 entry**.

Per l'analisi storica è stato usato in sola lettura lo **snapshot Git**
dell'ultima versione committata di `predictions.json`
(`commit 5df4a3a3e5c13580f667d9debcd7575e79232614`, 56 entry). Non è stato
ripristinato nel working tree e non è stato toccato.

## 2. Cutoff determinato dal repository (non inventato)

- Commit del fix: `ae8784d643575593f77241c54a1930e7bd48145f` (short `ae8784d`)
  - `fix(top-mix): elimina NG ~99.8% causato da lambda ~0 per neopromosse senza dati`
  - author timestamp: `2026-09-04 15:40:10 UTC`
  - introduce `PRIOR_MATCHES=6`, `_shrunk_ratio`, `_clip_lambda` NaN-safe.
- Merge in `main`: `dc192d5eaa36968380f8bde823ca1abe9792e65d` (short `dc192d5`)
  - `Merge pull request #10`
  - merge timestamp: `2026-09-04 16:50:17 UTC`

Politica di classificazione:
- salvato **prima** del commit di fix → pre-fix.
- salvato **dopo** il merge in `main` → post-fix (se ha `model_version`; in
  caso contrario resta legacy/ambiguo).
- salvato tra i due timestamp o senza `salvato_il` → **ambiguo**, non
  classificato automaticamente.

## 3. Modifiche implementate

- `SoccerMath/prediction_registry.py`: fonte unica delle costanti
  (`post_shrinkage_v1`, `pre_shrinkage`, `legacy`, `ambiguous`), parsing
  timestamp/stagione, classificazione, statistica separata, backup, tag.
- `SoccerMath/app.py`:
  - nuove predizioni ricevono automaticamente
    `model_version: "post_shrinkage_v1"` e
    `excluded_from_current_model_stats: false`;
  - `save_predictions` fa backup prima della scrittura e scrive locale
    **prima** di JSONBin;
  - tab `📒 Registro Predizioni & Tracking`: statistiche separate
    **Modello attuale** (`post_shrinkage_v1`) vs **Storico / pre-fix
    (audit)**, più totale registro complessivo;
  - colonna discreta `modello` con `✓ Modello attuale`, `⚠️ Pre-fix`,
    `Legacy`, `⚠️ Ambiguo`; tooltip con il testo richiesto.
- `audit/tag_pre_shrinkage_predictions.py`: script dry-run/`--apply`.
  Il remoto non viene mai sovrascritto senza `--push-remote`.
- `audit/test_prediction_registry.py`: test.

## 4. Dry-run sul registro disponibile

Comando eseguito:
```
python audit/tag_pre_shrinkage_predictions.py
```

Risultato:

| metrica | valore |
|---|---|
| Totale entry | **0** |
| da taggare `pre_shrinkage` | 0 |
| già `pre_shrinkage` | 0 |
| già `post_shrinkage_v1` | 0 |
| legacy/ambiguo | 0 |

(non esiste file locale né JSONBin configurato in questo ambiente)

### Dry-run sullo snapshot Git storico (riferimento)

```
python audit/tag_pre_shrinkage_predictions.py --source /tmp/predictions_5df4a3a.json
```

| metrica | valore |
|---|---|
| Totale entry | **56** |
| da taggare `pre_shrinkage` | **27** |
| già `pre_shrinkage` | 0 |
| già `post_shrinkage_v1` | 0 |
| legacy (stagioni precedenti) | **29** |
| ambiguo | 0 |
| intervallo `salvato_il` | 2026-05-02 15:24 UTC → 2026-08-26 09:31 UTC |

Le 27 entry pre-fix sono quelle di stagione **2026/2027** salvate in
agosto 2026. Le 29 legacy sono del 2025/2026.

## 5. Metriche del tab Registro

Con il registro reale disponibile (0 entry) non c'è alcun cambiamento
numerico.

Per lo snapshot Git di riferimento, la UI passerebbe da un'unica metrica
complessiva a due metriche separate:

- **Modello attuale (`post_shrinkage_v1`)**: totale 0, vinte 0, perse 0,
  in attesa 0.
- **Storico / pre-fix (audit)**: totale 56, vinte 20, perse 15,
  in attesa 21, win rate 57.1% (su 35 decise).
- **Totale registro complessivo**: rimane 56 / 20 / 15 / 21, win rate 57.1%.

Il win rate storico complessivo non viene cancellato: resta come metrica
separata. Le predizioni pre-fix non vengono nascoste.

## 6. Risultato test

```
python -m unittest audit.test_prediction_registry
```

Risultato: **16/16 OK**.

Copertura richiesta:
1. nessuna entry cancellata;
2. esito/risultato originali invariati;
3. probabilità originali invariate;
4. pre-fix correttamente taggati;
5. post-fix non taggati come pre-fix;
6. legacy gestiti esplicitamente;
7. statistica modello attuale esclude pre-fix;
8. statistica storico/audit include pre-fix;
9. metadati nuove predizioni contengono `post_shrinkage_v1`;
10. caricamento vecchi JSON senza `model_version` continua a funzionare.

## 7. Non eseguito / non modificato

- **Non** è stato eseguito `--apply`.
- **Non** è stato creato/ripristinato `predictions.json`.
- **Non** è stato scritto nulla su JSONBin.
- **Non** sono stati modificati pronostico, probabilità, risultato, esito,
  quota o timestamp.
