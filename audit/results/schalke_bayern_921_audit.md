# Audit diagnostico SoccerMath2.0

**Branch:** `arena/01a0727e-soccermath2-0`
**SHA:** `0695e9e611e481d2a9f5648a3a9fcd4412f86070`
**Snapshot dati:** lo stesso commit (`auto: archivio xG Understat + medie derivate 2026-09-05T16:14Z`). Lo stato attuale del working tree coincide con lo snapshot richiesto.
**Vincoli rispettati:** nessuna modifica a formule, soglie, pesi, JSONBin; nessun merge; sette mercati Top Mix invariati (1, X, 2, Over/Under 2.5, GG/NG). Nessuna funzione di salvataggio predizioni è stata chiamata.

Strumenti aggiunti (sola lettura): `audit/reconstruct_topmix_match.py`, `audit/inspect_topmix_registry.py`, test in `audit/test_reconstruct_topmix_match.py` e `audit/test_topmix_registry_tracking.py`, protocollo in `audit/topmix_selector_audit_protocol.md`.

---

## 1. Diagnosi del 92,1% — Schalke vs Bayern

### Esito

**Il 92,1% non è riproducibile sullo snapshot 0695e9e con le funzioni di produzione.** Non è stato forzato.

| | Mercato | `prob_val` (quello che l’app mostra) |
|---|---|---|
| Target dichiarato | (sconosciuto: manca la riga di registro) | **92,1%** |
| Selettore A di produzione, ora | Vittoria Bayern | **75,9%** |
| Gap | | **−16,2 punti** |

Calcolo A (identico a `fetch_and_calc_top_mix`):

- Poisson «Vittoria Bayern» = 76,79% (massimo dei sette)
- Elo «2» = 74,65%
- `confidence = 0.6 * 0.7679 + 0.4 * 0.7465 = 0.7594` → `round(..., 1) = 75.9`
- Filtri: `0.759 ≥ 0.55` e `|0.768 − 0.747| = 0.021 < 0.25` → ammesso

Il selettore B (stesse soglie, massimo ammissibile dopo i filtri) sceglie **lo stesso** mercato a 75,9%. Su *questa* partita l’ordine non cambia il risultato. Su un esempio sintetico nel test, A e B divergono: il protocollo serve proprio a misurare quanto succede sul pool, non su un singolo match.

### 1.1 Nomi ricevuti dall’API e nomi canonici

**Manca lo snapshot API** (nomi `shortName`/`name`, `match_id`, `utcDate`, status). I nomi sotto sono **assunzioni** allineate a football-data v4 e a `update_db.py` (`shortName or name`).

| Ruolo | Nome passato al motore (assunto) | `clean_name` | Risoluzione | In engine / xG / Elo / mercato |
|---|---|---|---|---|
| Casa | `Schalke` | `Schalke 04` | alias, mapped | sì / sì / sì / 80 |
| Trasferta | `Bayern` | `Bayern` | canonical, mapped | sì / sì / sì / 900 |

Candidati equivalenti (stesso Poisson a 1e-12): `Schalke`/`Schalke 04`/`Bayern`/`Bayern Munich`.

**Trappola di mapping (verificata sul codice, non sull’API):**
`clean_name("FC Bayern München")` → `"Bayern München"`, **non** in `team_stats` → fallback `{att: 1, def: 1}`. Su quel candidato il selettore A sceglie **GG 67,9%**, non la vittoria. Se l’API avesse usato `name` al posto di `shortName`, il 92,1% non sarebbe comunque uscito: uscirebbe un altro mercato più basso.

### 1.2 Corrispondenze CSV, xG, Elo

Verificate chiamando `get_league_engine`, `get_understat_xg`, `get_current_elo`, `get_league_db_files`.

**Schalke 04**

- CSV: 34 partite in `Bundesliga_2022.csv` (nome grezzo `Schalke 04`); 0 nel 2023–2025; **due righe** in `Bundesliga_Live.csv` il 30/08/2026 (`Augsburg`–`Schalke` e `Augsburg`–`Schalke 04`, stesso 3-0). Dopo `clean_name` + `drop_duplicates(keep='last')` il motore conta **una** partita live. Fallback gol: 35 partite.
- xG: chiave `Schalke 04` presente.
- Elo: 1457,6 (presente).

**Bayern**

- CSV: 34 partite/stagione 2022–2025 come `Bayern Munich`; 1 in Live come `Bayern` (28/08/2026 vs Stuttgart 5-1). Fallback gol: 137 partite.
- xG: chiave `Bayern` presente.
- Elo: 1821,6 (presente).

Nessun fallback `{att: 1, def: 1}` sul candidato principale.

### 1.3 Stagione, partite xG, medie

Stagione xG di produzione: **2026/2027** (`CURRENT_SEASON_START_YEAR=2026`). Le medie in `xg_bundesliga.json` sono derivate dall’archivio per-partita, **senza shrinkage** (lo shrinkage è solo in `get_league_engine`).

| Squadra | Partite xG incluse | xG_avg | xGA_avg | matches (file) |
|---|---|---|---|---|
| Schalke 04 | 1: Augsburg–Schalke 04, 2026-08-30 15:30Z, xG 1.837 / xGA 5.536, gol 0-3 | 1.837 | 5.536 | 1 |
| Bayern | 1: Bayern Munich–VfB Stuttgart, 2026-08-28 18:30Z, xG 4.079 / xGA 1.250, gol 5-1 | 4.079 | 1.250 | 1 |

Archivio: id 32254 e 32247, `is_result=true`. Fonte: `xg_archive.load_archive` + `season_averages`.

Medie di **lega xG** (stessa regola di `get_league_engine`: media sui valori finiti > 0, almeno 10 squadre, range 0.5–5.0):

- `league_xg = 2.196` (18 squadre)
- `league_xga = 2.104` (18 squadre)
- file xG usato: sì (verificato)

Medie gol del df concatenato (storici 2022–2025 + live, 1239 partite dopo dedup):

- `avg_h = 1.774`, `avg_a = 1.414` (verificate da `get_league_engine`)

Nota: il commit 0695e9e **non** cambia gli xG di Schalke e Bayern (restano 1 partita). Cambia le medie di lega perché altre squadre passano da 1 a 2 partite (`league_xg` 2.130 → 2.196). Lo shrinkage delle due rose si sposta di ~0.01: non spiega un salto a 92,1%.

### 1.4 Rapporti prima/dopo shrinkage

`PRIOR_MATCHES = 6`. Fonte forza: **xG con shrinkage** (non fallback gol). La traccia con `_shrunk_ratio` coincide con `att0_pure`/`def0_pure` dell’engine (tolleranza 1e-9).

| | attacco raw (xG / league) | attacco shrunk | difesa raw | difesa shrunk |
|---|---|---|---|---|
| Schalke 04 | 0.837 | **0.977** | 2.632 | **1.233** |
| Bayern | 1.858 | **1.123** | 0.594 | **0.942** |

Senza shrinkage i totali esploderebbero (difesa Schalke 2.63 × attacco Bayern 1.86). Con il prior da 6 partite i rapporti restano vicini a 1. **Non** è il bug NG ~99,8% (lambda ~0): qui i lambda sono grandi, non nulli.

### 1.5 Forma e valore di mercato

Forma = ultime 5 del df **multi-stagione** (produzione). Verificata ricostruendo le 5 righe dal df dell’engine.

**Schalke 04** (4 partite del **maggio 2023** + Augsburg 2026):

| Data | Dove | Avversario | GF | GS |
|---|---|---|---|---|
| 2023-05-05 | A | Mainz | 3 | 2 |
| 2023-05-13 | A | Bayern | 0 | 6 |
| 2023-05-20 | H | Ein Frankfurt | 2 | 2 |
| 2023-05-27 | A | Leipzig | 2 | 4 |
| 2026-08-30 | A | Augsburg | 0 | 3 |

`form att = 0.878` (clip 0.85–1.15), `form def = 1.15` (al cap). Non è la forma 2026/27.

**Bayern** (coda 2025/26 + live): Mainz 4-3, Heidenheim 3-3, Wolfsburg 1-0, Köln 5-1, Stuttgart 5-1. `form att = 1.15` (cap), `form def = 1.004`.

Mercato (tabella statica `MARKET_VALUES`, verificata):

- Schalke 04 = 80 → fattore 0.976
- Bayern = 900 → fattore 1.239 (non arriva al cap 1.25)

La forma e il mercato **non** entrano nella testa Totali (`att0_pure`). Entrano in 1X2.

### 1.6 Lambda delle due teste

Da `_stat_num` + le stesse formule di `get_full_poisson_two_heads`. Cross-check: `_two_heads_from_lambdas` riproduce la matrice Poisson a 1e-12.

| | Casa (Schalke) | Trasferta (Bayern) |
|---|---|---|
| Lambda 1X2 normalizzati (forma+mercato, somma ancorata alla base con forma) | 1.033 | 2.994 |
| Lambda Totali puri (xG shrunk, no forma, no mercato) | 1.632 | 1.957 |
| Clip `[exp(-6), exp(3)]` | non attivo | non attivo |

### 1.7 Probabilità Poisson dei sette mercati

| Mercato | Poisson |
|---|---|
| 1 Vittoria Schalke | 9,86% |
| X Pareggio | 13,34% |
| 2 Vittoria Bayern | **76,79%** (max) |
| Over 2.5 | 69,54% |
| Under 2.5 | 30,46% |
| GG | 69,09% |
| NG | 30,91% |

1+X+2 = 1; Over+Under = 1; GG+NG = 1.

### 1.8 Probabilità Elo 1X2

`predict_elo_probs("Schalke", "Bayern", "Bundesliga")`:

| 1 | X | 2 | elo_home | elo_away | diff (con HA 70) |
|---|---|---|---|---|---|
| 13,74% | 11,61% | **74,65%** | 1457,6 | 1821,6 | −294,0 |

Somma 1.000. Elo **non persistito**: è ricalcolato ora dai CSV dello snapshot. Non è un dump al click.

### 1.9 Mercato selezionato, filtri, punteggio finale

Selettore A (produzione): **Vittoria Bayern**, `prob_val=75.9`, ammesso.

Selettore B (diagnostico, stesse soglie):

| Mercato | Poisson | Confidence finale | Ammesso |
|---|---|---|---|
| Vittoria Schalke | 9,86% | 11,4% | no |
| Pareggio | 13,34% | 12,7% | no |
| Vittoria Bayern | 76,79% | **75,9%** | sì |
| Over 2.5 | 69,54% | 69,5% | sì |
| Under 2.5 | 30,46% | 30,5% | no |
| GG | 69,09% | 69,1% | sì |
| NG | 30,91% | 30,9% | no |

A e B concordano. Non c’è un 92,1% in nessuno dei sette.

### 1.10 Verificato / fallback / assunzione / mancante

**Verificato (funzioni di produzione + snapshot 0695e9e):** nomi canonici se l’API dà `Schalke`/`Bayern`; hit CSV/xG/Elo/mercato; xG 1 partita a testa; medie di lega; shrinkage; forma (con le 5 righe sopra); lambda; sette Poisson; Elo attuale dai CSV; selettore A → 75,9%.

**Fallback di produzione, non usato sul candidato principale:** `{att:1, def:1}` se il nome non mappa; gol al posto degli xG se manca `matches` o xG non valido; Elo 1500 se assente; mercato 50 se assente.

**Assunzioni:** `shortName` API = `Schalke` e `Bayern`; la partita era nella prossima giornata TIMED/SCHEDULED al click; il valore mostrato era `prob_val` e non un altro campo.

**Mancante — senza questi il 92,1% non si può confermare né smentire come bug di calcolo:**

1. Snapshot API football-data al momento del Top Mix (nomi, `match_id`, kickoff, status).
2. Dump Elo al click (abbiamo solo il ricalcolo dai CSV).
3. Riga JSONBin/registro (`prob_sicuro`, `mercato_standard`, `tipo`, `salvato_il`, posizione in classifica).
4. Contenuto della cache Streamlit (`get_league_engine` ttl 3600 s, `fetch_and_calc_top_mix` ttl 1800 s) su Cloud al momento del click.

Non si è cercato un insieme di soglie o di dati che «faccia uscire» 92,1%.

JSON macchina: `audit/results/schalke_bayern_921.json`.

---

## 2. Il Registro non permette di misurare il Top Mix

Ispezione **statica** di `app.py` / `prediction_registry.py` (AST). Nessun accesso a JSONBin. Dettaglio: `audit/results/topmix_registry_tracking.json`.

### 2.1 Come si distinguono Top Mix, Analisi Rapida, Billy

```text
tipo = "Top Mix" if "Top Mix" in pronostico else "Analisi"
```

| Origine | `pronostico_sicuro` | `tipo` persistito |
|---|---|---|
| Top Mix | `"{mercato} - Top Mix"` | Top Mix |
| Analisi Rapida | `"{mercato} - {p:.0%} - Poisson Auto"` | Analisi |
| Billy (Groq) | testo libero / `PRONOSTICO SICURO` | Analisi |
| Billy fallback / errore | `"{mercato} - Fallback"` / `"Errore AI"` | Analisi |

Non esiste un tipo `"Billy"` né un campo `origin`. Billy e Analisi Rapida sono indistinguibili dal solo `tipo`. Un filtro Registro su «Top Mix» dipende da una sottostringa nel pronostico, non da un identificativo di run.

### 2.2 Deduplica per `match_id`

```text
if any(p.get("match_id") == match_id for p in preds): return
```

Prima riga vince, **qualsiasi origine**. Conseguenze:

- Analisi Rapida (o Billy) salvata prima → il Top Mix della stessa partita **non viene scritto**.
- Top Mix salvato prima → Analisi Rapida/Billy non sovrascrivono.
- Un ricalcolo Top Mix **non aggiorna** mercato né probabilità: resta la prima previsione.
- Non c’è storico delle selezioni successive sullo stesso `match_id`.

Quindi il Registro **non è un log del selettore**. È un insieme di prime previsioni per partita.

### 2.3 Cache 30 minuti e partite nel frattempo iniziate

`@st.cache_data(ttl=1800)` su `fetch_and_calc_top_mix()` **senza argomenti**. La chiave di cache è vuota: un solo risultato globale per 30 minuti.

`select_next_matchday_matches` usa `datetime.now(timezone.utc)` **dentro** la funzione cachata. Il `now` resta quello del primo calcolo.

- Una partita che scade durante i 30 minuti resta nel Top Mix mostrato.
- Lo status API `IN_PLAY` non entra in un fetch fresco (`status=TIMED,SCHEDULED`), ma il risultato cached non rifà il fetch.
- Il salvataggio avviene **alla visualizzazione** (`save_prediction_entry` nel loop del tab), quindi una partita già iniziata può essere mostrata e, se il `match_id` non c’era, salvata.

`get_league_engine` ha ttl 3600 s: anche le forze possono essere di un’ora prima rispetto ai file xG appena committati.

### 2.4 Il toast «Top Mix salvati!» non verifica la scrittura remota

`save_predictions`:

1. Backup file locale.
2. Write locale.
3. `requests.put` JSONBin in `try/except: pass`, **senza leggere `status_code`**, senza assegnare la risposta.

Nel tab Top Mix, dopo il loop:

```text
st.success("✅ Top Mix salvati!")
```

Non è condizionato a: PUT 200, numero di insert > 0, presenza di `match_id`. Appare anche se tutte le righe sono state scartate dalla dedup, se `top_10` è vuoto, se JSONBin è down.

### 2.5 Schema minimo per monitorare le selezioni

Campi già presenti e riusabili: `match_id`, `home`, `away`, `campionato`, `giornata`, `data` (kickoff in italiano), `mercato_standard`, `prob_sicuro`, `salvato_il`, `model_version`, `tipo` (debole).

Campi **assenti**, necessari:

| Campo | Ruolo |
|---|---|
| `calculation_id` | un id per click/run Top Mix (le 10 righe condividono lo stesso) |
| `origin` | `top_mix` \| `analisi_rapida` \| `billy` (non una sottostringa) |
| `selector_version` | `A` produzione; `B` solo diagnostica, non in UI |
| `generated_at` | già coperto da `salvato_il` se si smette di usarlo come proxy |
| `kickoff_utc` | ISO; `data` resta per la UI |
| `probability` | `prob_sicuro` oggi è la confidence già mixata |
| `poisson` / `elo` | oggi calcolati nel Top Mix ma **non persistiti** |
| `position` | 1…10 nella graduatoria globale di quel `calculation_id` |
| `data_snapshot_sha` | commit dei CSV/xG usati (es. `0695e9e`) + `n` xG per squadra |

**Compatibilità:** campi aggiuntivi in coda al dict. I record vecchi restano leggibili (`model_label` già tollera l’assenza di `model_version`). La UI ignora le chiavi sconosciute.

**Non compatibile senza decisione esplicita:** continuare a deduplicare per solo `match_id`. Per misurare i ricalcoli serve o (a) più righe per `match_id` distinte da `calculation_id`, o (b) un log parallelo che non è il Registro. Non è stata implementata nessuna delle due (niente migrazione, niente persistenza nuova).

Verdetto: **`can_measure_top_mix_in_isolation = false`**.

---

## 3. Protocollo di audit del selettore

Testo operativo: `audit/topmix_selector_audit_protocol.md`.

Sintesi:

- Confronto **A** (max Poisson, poi mix Elo e filtri) vs **B** (probabilità finali di tutti i mercati, filtri, massimo ammissibile).
- Stessi modelli, dati, sette mercati, soglie (0.6/0.4, 0.55, 0.60, 0.25). Solo l’ordine cambia.
- Va riprodotta anche la selezione di giornata (`select_next_matchday_matches`), la graduatoria globale e il limite 10.
- Metriche: probabilità media vs hit rate sulle **stesse** selezioni concluse; Brier e calibrazione **dell’evento selezionato**; copertura e composizione mercato/lega; incertezza con cluster su `match_id` e giornata (partite ripetute, cache, ricalcoli).
- Un gap di calibrazione **non** è prova esclusiva di bias da selezione: va confrontato con la calibrazione dei sette mercati *prima* del selettore.

**Inventario stagioni già usate per scegliere modifiche** (non sono test intatti):

- 2022/23 e 2023/24: train.
- 2024/25: validation di forma-totali (`att0_pure`), due teste, shrinkage `PRIOR_MATCHES=6`, ensemble 0.6/0.4.
- 2025/26: test già consumato di quegli interventi.
- 2026/27: solo monitor prospettico, campione piccolo, già osservato per lo shrinkage.

**Non esiste un test storico non utilizzato.** Il protocollo propone validation storica *etichettata come già esaminata* più conferma prospettica. Non sostituire il motore live con un backtest a testa singola.

Impedimenti al replay storico: niente snapshot TIMED/SCHEDULED; niente timestamp di click; `MARKET_VALUES` non versionato; xG Understat rivisti; forma a 5 sul df multi-anno; Elo non dumpato; Registro cieco sul Top Mix.

Questo audit **non** ha lanciato il confronto A vs B sul passato e **non** ha cercato soglie.

---

## 4. Prossimo intervento minimo (consigliato, non eseguito)

**Tracciare le selezioni Top Mix**, non ritoccare soglie o pesi.

Motivazione: senza `calculation_id`, `origin`, posizione, Poisson/Elo separati e riferimento allo snapshot dati, il 92,1% non è ricostruibile dal Registro e il protocollo del selettore non ha un oggetto da misurare. Cercare un 92% «vero» cambiando il motore, o consumare 2024/25 come se fosse un hold-out, peggiorerebbe la contaminazione già documentata.

Intervento minimo, in un passo successivo:

1. Log diagnostico **locale** (non JSONBin) delle 10 righe di ogni run, col schema di §2.5.
2. Non cambiare la dedup del Registro finché non c’è una decisione esplicita su più predizioni per `match_id`.
3. Non mostrare B in UI.

Cosa **non** fare ora: merge; migrazione JSONBin; grid search soglie; chiamare 2024/25 o 2025/26 «test intatto».

---

## 5. Come è stato verificato

```text
python -m pytest audit/test_topmix_registry_tracking.py \
                 audit/test_reconstruct_topmix_match.py -q
# 28 passed

python audit/reconstruct_topmix_match.py --all-candidates \
    --output audit/results/schalke_bayern_921.json
```

Le ricostruzioni importano `app.get_league_engine`, `get_full_poisson_two_heads`, `_shrunk_ratio`, `predict_elo_probs`. Non chiamano `save_prediction_entry`, `save_predictions`, `load_predictions`, `fetch_and_calc_top_mix`.

Un workflow GitHub Actions in sola lettura (`.github/workflows/topmix_audit.yml`) può rifare test + ricostruzione e, se è presente `FOOTBALL_DATA_API_KEY`, una GET delle fixture attuali (nomi *odierni*, non lo snapshot del click). Artifact, `permissions: contents: read`, nessun segreto JSONBin.
