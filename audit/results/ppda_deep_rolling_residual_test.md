# PPDA e deep completions: archivio reale, archivio rolling point-in-time e test sul residuo

Referto unico per le tre parti della richiesta. Steso il `2026-09-16` e chiuso il
`2026-09-17` sul branch `arena/01a0aaed-soccermath2-0`, dopo il run di acquisizione
`35221939505` (commit `2c9edcb`), che ha committato nel repository l'evidenza di
copertura mancante.

**Verdetto in una riga:** l'archivio e' stato popolato davvero e i numeri di copertura
PPDA/deep coincidono con il referto di fattibilita' (7275/7276 partite complete, 0
mancanti, 1 PPDA strutturale); l'archivio rolling e' costruito e il test di leakage passa
a scarto 0; **ma il test sul residuo non trova segnale** — nessun fit per lega e'
significativo (p da 0.093 a 0.569), 2 coefficienti su 40 sotto 0.05 contro 2.0 attesi per
caso, e 6 covariate su 8 cambiano segno fra le leghe. Per il criterio dichiarato al punto
9 della richiesta, la pista si chiude qui: non c'e' nulla che giustifichi validation e
backtest.

**Il punto che era aperto e' chiuso, ed era un mio errore.** Nella stesura del 16 avevo
scritto che il secondo run si era concluso `success` e che le 224902 righe giocatore
restavano da verificare. Il run era invece **fallito** allo step di commit (causa
riprodotta e corretta in 0.4), quindi l'evidenza non era nel repository. Il run di
riparazione `35221939505` del 2026-09-17 l'ha committata (`audit/data/ppda_player_copertura.json`,
commit `2c9edcb`) e il conteggio e' ora verificato sul file: **224902 righe confermate
esattamente** sulle partite del perimetro, con 191 righe in piu' tutte spiegabili (6
partite di La Liga fuori perimetro, sezione 0.4).

Nessuna modifica al motore: `SoccerMath/app.py`, `SoccerMath/config.py`,
`SoccerMath/models/`, formule, soglie (`0.55`/`0.60`/`0.25`), pesi (`0.6`/`0.4`) e
`PRIOR_MATCHES` non sono toccati. Il motore viene solo LETTO (importato in sola
lettura dall'audit) per ricostruirne il lambda.

File prodotti da questo intervento:

| File | Che cos'e' |
|---|---|
| `.github/workflows/update_ppda_player.yml` | scheduler settimanale di acquisizione + commit (punto 2) |
| `SoccerMath/database/ppda_deep_<lega>.json` (5) | archivio reale acquisito da Understat (punto 1) |
| `audit/data/ppda_player_acquisizione.json`, `ppda_player_copertura.{json,md}` | evidenza di copertura committata dal run `35221939505` (righe giocatore comprese); nel checkout locale, verificata in 0.4 |
| `audit/build_ppda_deep_rolling.py` | archivio rolling point-in-time + test di leakage (punti 4-6) |
| `audit/data/ppda_deep_rolling.csv` (7282 righe) + `ppda_deep_rolling_summary.json` | archivio point-in-time |
| `audit/test_ppda_deep_rolling.py` | test offline del rolling (6 test, inclusa la prova che il test di leakage ha potere) |
| `audit/ppda_residual_test.py` | GLM Poisson sul residuo della testa Totali (punti 7-9) |
| `audit/data/ppda_residual_test.json` | risultati machine-readable del fit |

---

## Parte 0 — L'archivio reale

### 0.1 Due premesse della consegna che non tornano, e come sono state risolte

**(a) "storico completo dal 2014 come nel referto di fattibilita'".** Il referto di
fattibilita' non usa il 2014. Il suo campo `acquisition.seasons` e'
`["2223","2324","2425","2526","2627"]`, la costante `SEASONS` di
`update_all_ppda_player_db.py:143` e' la stessa, e il denominatore di copertura e'
l'archivio xG committato, che parte dalla 2022/23. I numeri da confermare
(7275/7276, 224902) valgono **solo** su quel perimetro: acquisendo dal 2014 il
denominatore cambierebbe e il confronto perderebbe significato.

Verificato in locale sul repository: il perimetro dell'archivio xG committato, ricalcolato
con `ppda_deep_player_audit.xg_perimeter`, e'

| Lega | 2022 | 2023 | 2024 | 2025 | 2026 | totale |
|---|---|---|---|---|---|---|
| Serie A | 380 | 380 | 380 | 380 | 40 | 1560 |
| Premier League | 380 | 380 | 380 | 380 | 40 | 1560 |
| La Liga | 380 | 380 | 380 | 380 | 51 | 1571 |
| Bundesliga | 306 | 306 | 306 | 306 | 27 | 1251 |
| Ligue 1 | 380 | 306 | 306 | 306 | 36 | 1334 |
| **totale** | | | | | | **7276** |

Quindi le stagioni acquisite sono `2223 2324 2425 2526 2627`, come nel run verificato
(confermato dall'utente durante la lavorazione). Se in futuro si vuole lo storico dal
2014 va chiesto esplicitamente con l'input `seasons` del workflow, sapendo che i numeri
non saranno piu' confrontabili con questi.

**(b) "esegui `update_all_ppda_player_db.py` per davvero".** In questo ambiente di
lavoro non si puo': l'egresso di rete e' limitato a PyPI e GitHub, e
`https://understat.com/` restituisce `TLS/SSL connection has been closed (EOF)`
(misurato, non assunto). L'acquisizione reale e' quindi stata eseguita su GitHub
Actions — lo stesso posto in cui e' stata eseguita quella del referto di fattibilita' —
da un workflow che committa i risultati sul branch. Run:
https://github.com/iFelice/SoccerMath2.0/actions/runs/35120920395 (conclusione
`success`, acquisizione 16:18:02 → 16:58 UTC del 2026-09-16).

Anche la lettura dei log e degli artifact del run e' bloccata da qui
(`results-receiver.actions.githubusercontent.com` e `*.blob.core.windows.net`
rispondono `EOF`): per questo il workflow committa l'evidenza di copertura in
`audit/data/` invece di lasciarla solo nell'artifact, che scade dopo 14 giorni.

### 0.2 File committati e identita' con il run verificato

| Lega | File | Byte | sha256 (16) | sha256 nel referto di fattibilita' | Identico |
|---|---|---|---|---|---|
| Serie A | `ppda_deep_serie_a.json` | 450120 | `2acfb99bf40a830e` | `2acfb99bf40a830e` | **si'** |
| Premier League | `ppda_deep_premier_league.json` | 463348 | `dd51b5ec836a0197` | `dd51b5ec836a0197` | **si'** |
| La Liga | `ppda_deep_la_liga.json` | 462556 | `7eee2846a183a809` | `57c71447ead0c3c8` | no |
| Bundesliga | `ppda_deep_bundesliga.json` | 374921 | `0319d545ee4696a6` | `0319d545ee4696a6` | **si'** |
| Ligue 1 | `ppda_deep_ligue_1.json` | 385927 | `68f9bc12d2a9aee9` | `68f9bc12d2a9aee9` | **si'** |

Totale 2.0 MiB. Quattro file su cinque sono **byte per byte identici** a quelli
dell'acquisizione verificata del 2026-09-15 (hash ricalcolati con `sha256sum` sul checkout
attuale): la fonte non ha rivisto nulla in quelle leghe. La Liga differisce perche' ha
**6 partite in piu'** (vedi sotto): tre acquisite il 2026-09-16, tre il 2026-09-17 dal run
`35221939505`. Il suo hash intermedio del 16 (`8c2737dc376b5597`, 1574 record) e'
sostituito da quello attuale (`7eee2846a183a809`, 1577 record).

### 0.3 Copertura, ricalcolata in locale sui file committati

Eseguito `audit/ppda_deep_player_audit.py --database-dir SoccerMath/database
--xg-dir SoccerMath/database --datasets ppda_deep` sui file appena committati
(quit code 0). Denominatore: partite concluse con entrambi gli xG nell'archivio xG
committato.

| Lega | Perimetro | Con record | Complete | Parziali | PPDA non calcolabile | Senza record | Mancanti | Copertura completa |
|---|---|---|---|---|---|---|---|---|
| Serie A | 1560 | 1560 | 1560 | 0 | 0 | 0 | 0 | 100.0% |
| Premier League | 1560 | 1560 | 1560 | 0 | 0 | 0 | 0 | 100.0% |
| La Liga | 1571 | 1577 | 1571 | 0 | 0 | 0 | 0 | 100.0% |
| Bundesliga | 1251 | 1251 | 1250 | 0 | 1 | 0 | 0 | 99.9% |
| Ligue 1 | 1334 | 1334 | 1334 | 0 | 0 | 0 | 0 | 100.0% |
| **totale** | **7276** | **7282** | **7275** | **0** | **1** | **0** | **0** | **99.99%** |

**Confronto con il referto di fattibilita' (punto 3):**

| Grandezza | Referto 2026-09-15 | Oggi, sui file committati | Esito |
|---|---|---|---|
| perimetro (concluse con xG) | 7276 | 7276 | coincide |
| PPDA/deep completi | 7275 | 7275 | coincide |
| partite senza record | 0 | 0 | coincide |
| PPDA non calcolabile (denominatore difensivo 0) | 1 (Bundesliga) | 1 (Bundesliga) | coincide |
| righe giocatore-partita | 224902 | 224902 sul perimetro, +191 fuori perimetro | **coincide sul perimetro** (0.4) |

Le 6 partite in piu' sono tutte di La Liga (1577 record contro un perimetro di 1571) e
sono identificate una per una:

| id Understat | Stagione | Kickoff | Partita | PPDA casa/trasferta | Deep casa/trasferta |
|---|---|---|---|---|---|
| 30829 | 2026 | 2026-09-15 17:00 | Rayo Vallecano - Espanyol | 12.69 / 12.45 | 4 / 9 |
| 30821 | 2026 | 2026-09-15 18:00 | Alaves - Valencia | 13.04 / 10.65 | 5 / 7 |
| 30825 | 2026 | 2026-09-15 19:30 | Elche - Real Madrid | 9.76 / 21.00 | 11 / 20 |
| 30822 | 2026 | 2026-09-16 17:00 | Atletico Madrid - Osasuna | 8.48 / 12.04 | 18 / 2 |
| 30824 | 2026 | 2026-09-16 17:00 | Deportivo La Coruna - Sevilla | 8.11 / 8.11 | 5 / 8 |
| 30826 | 2026 | 2026-09-16 19:30 | Barcelona - Racing Santander | 8.04 / 28.00 | 19 / 2 |

Il meccanismo verificato sull'archivio xG committato: le sei partite **ci sono**, come
righe di calendario della stagione 2026, ma con `is_result=false` e `home_goals`,
`away_goals`, `home_xg`, `away_xg` tutti nulli (verificato riga per riga su
`xG archivio la liga.json`), quindi non entrano nel perimetro ("concluse con entrambi gli
xG"). L'ultima partita di La Liga conclusa con xG nell'archivio committato e'
`2026-09-14 19:00 Villarreal - Real Betis`. In altre parole l'archivio PPDA/deep e'
**avanti di due giornate** rispetto all'archivio xG per la sola La Liga, che ha giocato
lunedi 15 e martedi 16 settembre: l'aggiornamento xG di `update_xg.yml` gira martedi e
venerdi alle 06:00 UTC, quindi martedi 15 alle 06:00 era precedente a tutte e sei. Le
altre quattro leghe hanno l'ultima partita il 13-14 settembre, gia' dentro l'archivio xG.

Non sono partite "in piu' dentro il perimetro": il perimetro resta 1571, la copertura
resta 100%, e le partite del perimetro assenti dal file sono **0**.

Valori acquisiti (per contesto, non sono soglie): PPDA mediana 11.48, p05 5.50,
p95 25.55, minimo 2.30, massimo 193.00, 2 valori non calcolabili su 14564
squadra-partite (14562 valori validi); deep completions mediana 6.00, p05 1.00, p95 15.00,
massimo 37.00, 309 zeri. Ricalcolati oggi sui file attuali: le sei partite di La Liga non
spostano nessun estremo.

### 0.4 Statistiche giocatore (i file `player_match_<lega>.json`)

Acquisiti e validati negli stessi run dei PPDA/deep (lo script fa fallire la lega se la
copertura non rientra nelle soglie dichiarate), ma **non committati**: pesano ~91 MB e
nessuna parte del motore o di questa analisi li legge. Restano negli artifact dei run
(14 giorni) e i loro conteggi per lega devono finire nell'evidenza committata
`audit/data/ppda_player_acquisizione.json` / `ppda_player_copertura.{json,md}`.

**Correzione a una affermazione della prima stesura di questo referto.** Avevo scritto
che il secondo run (`35125626021`) si era concluso `success`. E' falso: l'API di Actions
riporta `conclusion: failure`, fallito allo step "Commit e push"
(`updatedAt 2026-09-16T17:48:14Z`). L'acquisizione, l'audit, la pubblicazione dei
ppda_deep e l'artifact erano andati a buon fine; a fallire e' stato il commit.

Causa, riprodotta in locale e non dedotta: la rete di sicurezza che avevo scritto nel
workflow pretendeva che ogni commit contenesse almeno un file `ppda_deep`, ma nel secondo
run quei file erano **identici** a quelli del run precedente (nessuna partita nuova fra le
16:58 e le 17:48 UTC) e quindi `git add` non metteva nulla in staging: con la sola evidenza
di copertura staged, lo step usciva 1 con `::error::nessun file ppda_deep nel commit`.
Riproduzione deterministica dello step su un clone temporaneo, con ppda_deep invariati e
evidenza modificata: `exit code 1`. Con il fix (`git diff --cached --quiet` controllato per
primo, e l'assenza di ppda_deep declassata da errore a messaggio) lo stesso caso committa:
`Nessuna partita nuova nei ppda_deep: committata solo l'evidenza di copertura.`

Conseguenza, al momento della stesura del 16: l'evidenza con i conteggi delle righe
giocatore non era nel repository, e non era leggibile nemmeno dall'artifact perche' gli
host di storage di Actions non sono raggiungibili da questo ambiente (misurato di nuovo il
17: `productionresultssa9.blob.core.windows.net` risponde `EOF`, sia per gli artifact sia
per i log). Da qui il run di riparazione, tracciato qui sotto. Il workflow corretto e'
quello ora committato in `.github/workflows/update_ppda_player.yml`, e ha funzionato al
primo colpo.

**Verifica chiusa il 2026-09-17 sul run `35221939505`** (conclusion `success`, verificata
via `gh api .../actions/runs/35221939505`, step "Commit e push" `success`, commit
`2c9edcb`). L'evidenza e' ora nel repository e leggibile dal checkout:
`audit/data/ppda_player_copertura.json` (178137 byte, sha256 `4de92a977b99c19d`) e
`ppda_player_acquisizione.json` (53287 byte, sha256 `02ed9361fe603b15`). Il run ha usato
soccerdata **1.9.1**, le stesse cinque stagioni `2223 2324 2425 2526 2627` e lo stesso
denominatore (archivio xG committato, 7276 partite).

| Lega | Perimetro | Partite con righe | Righe giocatore oggi | Righe nel referto di fattibilita' | Differenza |
|---|---|---|---|---|---|
| Serie A | 1560 | 1560 | 48884 | 48884 | **0** |
| Premier League | 1560 | 1560 | 47022 | 47022 | **0** |
| La Liga | 1571 | 1577 | 49385 | 49194 | **+191** |
| Bundesliga | 1251 | 1250 | 38910 | 38910 | **0** |
| Ligue 1 | 1334 | 1334 | 40892 | 40892 | **0** |
| **totale** | **7276** | **7281** | **225093** | **224902** | **+191** |

**Le 224902 righe sono confermate.** Quattro leghe su cinque tornano al rigore, e la
differenza della quinta e' spiegata interamente, non approssimata. Il campo `rows`
dell'audit conta le righe di **tutte** le partite presenti nel file, non solo quelle del
perimetro; La Liga oggi ne ha 6 fuori perimetro (sezione 0.3). La verifica per stagione lo
isola senza ambiguita':

| Stagione La Liga | Partite perimetro | Partite presenti | Righe oggi | Righe nel referto | Differenza |
|---|---|---|---|---|---|
| 2022 | 380 | 380 | 11837 | 11837 | **0** |
| 2023 | 380 | 380 | 11888 | 11888 | **0** |
| 2024 | 380 | 380 | 11900 | 11900 | **0** |
| 2025 | 380 | 380 | 11952 | 11952 | **0** |
| 2026 | 51 | 57 | 1808 | 1617 | **+191** |

Le quattro stagioni storiche (47577 righe) sono identiche al rigore: la fonte non ha
rivisto nulla. Le 191 righe in piu' stanno tutte nella stagione 2026 e corrispondono alle
6 partite fuori perimetro: 191 / 6 = **31.8 righe per partita**, contro le 31.7 della
mediana di La Liga nel referto di fattibilita'. In altre parole 224902 + 191 = 225093, e
il "+191" e' la conseguenza attesa di un archivio che ha due giornate di La Liga in piu'
rispetto all'archivio xG, non una revisione del dato.

Lo stesso run conferma la copertura PPDA/deep: 7276 perimetro, 7275 completi, 1 PPDA
strutturale (Bundesliga), 0 mancanti. I conteggi del report di acquisizione
(`ppda_player_acquisizione.json`, campo `datasets.player_match.rows`) e quelli
dell'audit di copertura coincidono lega per lega, quindi i numeri non dipendono da uno
solo dei due strumenti.

Conseguenza pratica: l'archivio giocatore e' utilizzabile, ma la sua copertura va letta
sul perimetro (100% tranne 1 partita Bundesliga) e non sul totale dei record.


### 0.5 Scheduler (punto 2)

`.github/workflows/update_ppda_player.yml`, stesso pattern di `update_xg.yml`:

- `schedule: cron '0 5 * * 1'` (lunedi 05:00 UTC, prima della pipeline xG di martedi e
  venerdi, cosi' il denominatore e' l'archivio xG della settimana);
- `workflow_dispatch` con input (stagioni, parallelismo, tolleranza, `commit_ppda`);
- `push` su `arena/**` sul proprio path: un workflow presente solo su un branch non di
  default non e' avviabile da `workflow_dispatch`, e' lo stesso espediente gia' usato da
  `ppda_player_verify.yml`;
- `permissions: contents: write`, `concurrency: soccermath-data` con
  `cancel-in-progress: false` (lo stesso gruppo di `update_xg.yml` e
  `update_database.yml`: i tre workflow committano sullo stesso branch);
- test offline della pipeline prima di scaricare, acquisizione con validazione e
  scrittura atomica, audit di copertura, commit con retry e rebase se il branch si muove;
- rete di sicurezza sul commit: entrano solo `SoccerMath/database/ppda_deep_*.json` e i
  tre file di evidenza in `audit/data/`, qualunque altro path staged fa fallire lo step.

Tolleranza dichiarata: `--missing-tolerance-ratio 0.01` (lo stesso valore del run
verificato; lo script di suo ha tolleranza 0). Il report dice quante partite mancano e
perche'.

---

## Parte 1 — Archivio point-in-time rolling (`audit/build_ppda_deep_rolling.py`)

### 1.1 Che cosa calcola

Per ogni partita e per ogni squadra in campo, la media mobile delle ultime N partite di
quella squadra con kickoff **strettamente precedente**, su quattro misure:

| Misura | Significato |
|---|---|
| `own_ppda` | PPDA proprio (pressione della squadra) |
| `own_deep` | deep completions generati |
| `faced_ppda` | PPDA subito (PPDA dell'avversario in quelle partite) |
| `faced_deep` | deep completions subiti |

con **N=5 e N=10 entrambe**, come richiesto: la finestra non viene scelta a priori.
Output: `audit/data/ppda_deep_rolling.csv`, **7282 righe** (una per partita), 0 problemi
di parsing, 0 nomi di squadra non risolti, 0 kickoff senza orario. Ricostruito il
2026-09-17 sull'archivio aggiornato dal run `35221939505` (La Liga da 1574 a 1577
partite); le tre partite nuove sono della stagione 2026 e non toccano il train della
Parte 2.

### 1.2 Finestre non piene: trattamento dichiarato, nessun riempimento silenzioso

| Caso | Trattamento | Perche' |
|---|---|---|
| `n < 3` partite precedenti | **NaN** su tutte e quattro le misure, `status="insufficient"` | non si inventa un valore; e' il caso delle prime giornate della 2022/23, dove l'archivio PPDA/deep non ha alcuno storico precedente perche' parte dalla 2022/23 |
| `3 <= n < N` | media sulle n partite disponibili, `status="partial"`, `n` scritto in riga | e' una finestra corta dichiarata, non una media di lega e non un'imputazione |
| `n >= N` | `status="full"` | |
| PPDA non calcolabile (`null` nel sorgente) | escluso dalla media, `n_own_ppda` dice quanti valori sono entrati; se la finestra non ne ha nessuno il risultato e' NaN, mai 0 | `pd.NA` strutturale di soccerdata (denominatore difensivo nullo) |

Nessuna media di lega, nessun carry-forward. Chi consuma l'archivio vede `n`, `n_<misura>`
e `status` per ogni lato e finestra.

La finestra **non si azzera a inizio stagione**, quindi puo' contenere partite della
stagione precedente. Per questo ogni riga riporta `*_age_days`, l'eta' della partita piu'
vecchia in finestra: mediana 78.9 giorni (N=10), p90 154.2, p99 495.6, massimo 1253.1;
le finestre con una partita piu' vecchia di 400 giorni sono 79 su 7219 (1.09%). Sono i
casi di squadra retrocessa e ripromossa: la finestra pesca il suo stint precedente. E'
visibile invece che nascosto; un tetto di eta' (il progetto usa 400 giorni in
`PT_AGE_CAP`) sarebbe la raffinatura naturale, ma e' una scelta di modello e qui non
viene fatta.

Conteggio degli stati nel **train** (lato casa; il lato trasferta e' nel JSON):

| Lega | r5 full / partial / insufficient | r10 full / partial / insufficient |
|---|---|---|
| Serie A | 701 / 23 / 34 | 643 / 81 / 34 |
| Premier League | 701 / 23 / 36 | 645 / 79 / 36 |
| La Liga | 702 / 22 / 35 | 644 / 80 / 35 |
| Bundesliga | 563 / 20 / 29 | 512 / 71 / 29 |
| Ligue 1 | 629 / 22 / 32 | 573 / 78 / 32 |

### 1.3 Test di leakage (punto 6): eseguito, non assunto

`build_ppda_deep_rolling.py --leakage-sample 25` campiona 25 partite per lega fra quelle
con finestra piena a N=10 e, per ciascuna, ricostruisce l'intero archivio due volte:

- **(a) troncamento**: dal sorgente spariscono tutte le partite con kickoff >= quello
  della partita campione (resta la partita campione, senza la quale non esiste la riga);
- **(b) iniezione**: al sorgente vengono **aggiunte** 18 partite sintetiche estreme per
  campione (PPDA 999 e 0.001, deep completions 999, con le stesse due squadre) con
  kickoff >= quello della partita campione.

Risultato: **125 partite campionate, 2250 partite future iniettate, scarto massimo 0.0,
0 differenze** su tutte le colonne rolling di entrambe le finestre.

| Lega | Partite nel file | Con finestra piena a N=10 | Campionate |
|---|---|---|---|
| Serie A | 1560 | 1392 | 25 |
| Premier League | 1560 | 1401 | 25 |
| La Liga | 1577 | 1403 | 25 |
| Bundesliga | 1251 | 1105 | 25 |
| Ligue 1 | 1334 | 1191 | 25 |

**Prova che il test ha potere** (`audit/test_ppda_deep_rolling.py::test_leakage_test_ha_potere`):
sostituendo `rolling_values` con una versione che include la partita stessa nella propria
finestra, lo stesso test restituisce 40 differenze con scarto massimo 6.04. Il test non
e' vacuo: cattura una finestra che guarda avanti.

Verificati a mano sul fixture anche: la media mobile usa solo il passato (partita 104:
`own_ppda` = media di 10,11,12,13 = 11.5, non 14.0), `n<3` da' NaN, il PPDA nullo e'
escluso dalla media (media 12.0 su 2 valori, non 0.0), e una partita dello stesso giorno
senza orario resta fuori dalla finestra. `python -m pytest
audit/test_ppda_deep_rolling.py -q` → **6 passed**.

---

## Parte 2 — Test sul residuo della testa Totali (`audit/ppda_residual_test.py`)

### 2.1 Il lambda "attuale del motore live", ricostruito e verificato

Per ogni partita, walk-forward in ordine cronologico (medie gol progressive e stato
squadra aggiornati **dopo** la partita), fonte F_season al cutoff della partita — la
stessa fonte point-in-time di `app.get_league_engine` — shrinkage `PRIOR_MATCHES=6`
verso la media di lega della stagione in corso, fallback gol per le squadre senza
partite in stagione. Poi

```
base_pure_casa      = att0_pure_casa * def0_pure_trasferta * avg_h
base_pure_trasferta = att0_pure_trasferta * def0_pure_casa * avg_a
lambda              = clip(base_pure, exp(-6), exp(3))       # _clip_lambda di app.py
```

Non e' un'assunzione che questo sia il lambda di produzione: la Under 2.5 e il GG calcolati
da `app.get_full_poisson_two_heads` su questi lambda sono stati confrontati partita per
partita con la ricostruzione diretta.

| Lega | Partite | max &#124;U2.5 motore − U2.5 ricostruita&#124; | max &#124;GG motore − GG ricostruito&#124; |
|---|---|---|---|
| Serie A | 1560 | 0.0 | 0.0 |
| Premier League | 1560 | 0.0 | 0.0 |
| La Liga | 1574 | 0.0 | 0.0 |
| Bundesliga | 1251 | 0.0 | 0.0 |
| Ligue 1 | 1334 | 0.0 | 0.0 |

Identita' esatta, non approssimazione.

Prima giornata del walk-forward esclusa dal fit primario e contata: non ha ancora una
giornata completa di storico, e le medie gol provvisorie producono lambda irriconoscibili
(misurato in Serie A: prima partita `lambda_total` 0.20 con 6 gol, poi 6.00 / 4.00 / 3.67
sulle successive nove, perche' la media gol dopo una sola partita e' 4.0). Sono 10 partite
per lega e 9 in Bundesliga: 49 su 3578 partite di train (1.4%), e il train usato dal fit
primario e' quindi 3529 partite. Il fit su tutto il train e' comunque riportato
come robustezza nel JSON (`glm_all_train`).

### 2.2 Unione con le feature rolling

Chiave: lega + giorno locale del kickoff + squadra casa + squadra trasferta, con i nomi
canonici del resolver condiviso della PR #15. Verificato preliminarmente che i 27/27/29/25/25
nomi dei CSV football-data sono tutti nomi canonici noti a `team_names` (0 non risolti).

| Lega | Partite | Agganciate | Non agganciate | di cui nel train |
|---|---|---|---|---|
| Serie A | 1560 | 1557 | 3 | 2 |
| Premier League | 1560 | 1560 | 0 | 0 |
| La Liga | 1574 | 1572 | 2 | 1 |
| Bundesliga | 1251 | 1250 | 1 | 0 |
| Ligue 1 | 1334 | 1322 | 12 | 3 |
| **totale** | **7279** | **7261** | **18** | **6** |

Le 18 non agganciate sono elencate tutte in `audit/data/ppda_residual_test.json`
(`join.unmatched_all`) e le ho verificate **una per una** contro l'archivio PPDA/deep: per
ognuna ho cercato la stessa coppia di squadre nella stessa lega e ho misurato lo scarto di
data. Esito: 17 su 18 sono un disaccordo di **data**, 1 e' un disaccordo di **campo**.

| Lega | Stagione | Data CSV | Partita (CSV) | Data Understat | Scarto |
|---|---|---|---|---|---|
| Serie A | 2023/24 | 2024-04-25 | Udinese-Roma | 2024-04-14 | **−11 gg** |
| Serie A | 2023/24 | 2024-05-23 | Cagliari-Fiorentina | 2024-05-24 | +1 |
| Serie A | 2024/25 | 2025-05-17 | Genoa-Atalanta | 2025-05-18 | +1 |
| La Liga | 2023/24 | 2023-12-11 | Granada-Ath Bilbao | 2023-12-12 | +1 |
| La Liga | 2025/26 | 2025-09-30 | Valencia-Oviedo | 2025-09-29 | −1 |
| Bundesliga | 2024/25 | 2024-11-29 | St Pauli-Holstein Kiel | 2024-11-30 | +1 |
| Ligue 1 | 2022/23 | 2023-04-28 | Strasbourg-Lyon | 2023-04-30 | +2 |
| Ligue 1 | 2023/24 | 2023-08-11 | Nice-Lille | 2023-08-12 | +1 |
| Ligue 1 | 2023/24 | 2023-08-13 | Brest-Lens | 2023-08-12 | −1 |
| Ligue 1 | 2025/26 | 2026-02-06 | Metz-Lille | 2026-02-08 | +2 |
| Ligue 1 | 2025/26 | 2026-02-07 | Lens-Rennes | 2026-02-08 | +1 |
| Ligue 1 | 2025/26 | 2026-02-07 | Brest-Lorient | 2026-02-08 | +1 |
| Ligue 1 | 2025/26 | 2026-02-07 | Nantes-Lyon | 2026-02-08 | +1 |
| Ligue 1 | 2025/26 | 2026-05-02 | Nantes-Marseille | 2026-05-03 | +1 |
| Ligue 1 | 2025/26 | 2026-05-02 | PSG-Lorient | 2026-05-03 | +1 |
| Ligue 1 | 2025/26 | 2026-05-02 | Metz-Monaco | 2026-05-03 | +1 |
| Ligue 1 | 2025/26 | 2026-05-02 | Nice-Lens | 2026-05-03 | +1 |
| Ligue 1 | 2026/27 | 2026-08-23 | Rennes-PSG | 2026-08-23 | 0 gg, **campo invertito** |

I tre meccanismi, tutti verificati sui file:

- **partita rinviata e recuperata** (Udinese-Roma): Understat conserva la data
  originariamente calendarizzata, football-data quella effettiva. −11 giorni;
- **disallineamento di 1-2 giorni** (16 partite, quasi tutte Ligue 1): la stessa partita ha
  date diverse nei due archivi. Nell'archivio PPDA/deep la prima giornata 2023/24 di Ligue 1
  compare tutta alle `18:00:00` del 2023-08-12, un orario ripetuto che ha l'aria di un
  default della fonte; lo stesso identico difetto e' nell'archivio xG committato, quindi
  non e' introdotto da questa pipeline;
- **campo invertito** (Rennes-PSG del 2026-08-23): football-data ha Rennes in casa, mentre
  Understat e l'archivio xG committato hanno `Paris Saint Germain - Rennes` (id 31948,
  0-0, xG 0.630/0.911), con il ritorno calendarizzato al 2027-03-06. Una delle due fonti ha
  il campo sbagliato; qui non si arbitra, la partita resta fuori ed e' dichiarata.

Nessuna tolleranza fuzzy sulla data o sul campo: una partita non agganciata resta fuori.
Impatto sul fit: **6 partite nel train** (0.17% delle 3578 partite di train delle cinque
leghe); dieci delle dodici di Ligue 1 sono nelle stagioni 2025/26 e 2026/27, fuori dal
train.

Le partite escluse dal fit per feature mancanti si dividono cosi' (la distinzione e' nel
JSON, `fit_dropped_breakdown`):

| Lega | Escluse | partita non agganciata | finestra insufficiente |
|---|---|---|---|
| Serie A | 31 | 2 | 29 |
| Premier League | 29 | 0 | 29 |
| La Liga | 30 | 1 | 29 |
| Bundesliga | 24 | 0 | 24 |
| Ligue 1 | 30 | 3 | 27 |

La quasi totalita' sono le prime giornate della 2022/23, dove l'archivio PPDA/deep non ha
storico precedente: non sono dati persi, e' il bordo sinistro dell'archivio.

### 2.3 Il modello

GLM Poisson su **train 2022/23 + 2023/24**, risposta = gol totali della partita,
`offset = log(lambda_casa + lambda_trasferta)` della testa Totali di produzione, covariate
= le 8 feature rolling. Coerentemente con un offset sui gol totali, ogni covariata e' la
**somma dei due lati** (attacco proprio = attacco casa + attacco trasferta; difesa subita =
cio' che le due squadre subiscono), dichiarata in `match_covariates`.

Partite escluse dal fit per feature mancanti: Serie A 31, Premier 29, La Liga 30,
Bundesliga 24, Ligue 1 30 (composizione nella tabella della sezione 2.2).

Calibrazione del solo offset (senza covariate) sul train: rapporto gol medi / lambda medio
= 1.020 (Serie A), 1.061 (Premier), 1.025 (La Liga), 1.008 (Bundesliga), 0.951 (Ligue 1);
dispersione di Pearson del fit 0.889 / 0.982 / 1.030 / 0.952 / 0.991. Il lambda di
produzione e' gia' ben calibrato in livello: il residuo da spiegare e' piccolo.

### 2.4 Risultati per lega (5 fit indipendenti, punto 9)

Test del rapporto di verosimiglianza delle 8 covariate contro il modello di solo offset:

| Lega | n | LR (8 gdl) | **p** | Dispersione |
|---|---|---|---|---|
| Serie A | 719 | 11.13 | **0.195** | 0.889 |
| Premier League | 721 | 9.62 | **0.292** | 0.982 |
| La Liga | 720 | 13.59 | **0.0931** | 1.030 |
| Bundesliga | 579 | 6.71 | **0.569** | 0.952 |
| Ligue 1 | 646 | 10.89 | **0.208** | 0.991 |

Nessuna lega e' significativa. Coefficienti (beta sul lambda totale, errore standard, p;
`beta_std` = stessa regressione su covariate z-score, per confrontare le scale):

**Serie A** (n=719)

| Covariata | beta | se | z | p | beta_std |
|---|---|---|---|---|---|
| own_ppda_5 | +0.01650 | 0.00777 | 2.12 | **0.0338** | +0.0915 |
| own_deep_5 | −0.02060 | 0.01668 | −1.24 | 0.217 | −0.0680 |
| faced_ppda_5 | +0.01245 | 0.00846 | 1.47 | 0.141 | +0.0815 |
| faced_deep_5 | −0.01934 | 0.01735 | −1.11 | 0.265 | −0.0528 |
| own_ppda_10 | −0.01215 | 0.00950 | −1.28 | 0.201 | −0.0558 |
| own_deep_10 | +0.03675 | 0.01966 | 1.87 | 0.0616 | +0.1072 |
| faced_ppda_10 | −0.01151 | 0.00997 | −1.15 | 0.249 | −0.0670 |
| faced_deep_10 | +0.02466 | 0.02113 | 1.17 | 0.243 | +0.0578 |

**Premier League** (n=721)

| Covariata | beta | se | z | p | beta_std |
|---|---|---|---|---|---|
| own_ppda_5 | +0.00278 | 0.00643 | 0.43 | 0.666 | +0.0196 |
| own_deep_5 | +0.00125 | 0.01228 | 0.10 | 0.919 | +0.0060 |
| faced_ppda_5 | +0.00028 | 0.00665 | 0.04 | 0.966 | +0.0022 |
| faced_deep_5 | −0.00151 | 0.01191 | −0.13 | 0.899 | −0.0059 |
| own_ppda_10 | +0.00230 | 0.00783 | 0.29 | 0.769 | +0.0145 |
| own_deep_10 | +0.01921 | 0.01447 | 1.33 | 0.184 | +0.0849 |
| faced_ppda_10 | −0.00806 | 0.00774 | −1.04 | 0.298 | −0.0583 |
| faced_deep_10 | +0.00569 | 0.01516 | 0.38 | 0.708 | +0.0190 |

**La Liga** (n=720)

| Covariata | beta | se | z | p | beta_std |
|---|---|---|---|---|---|
| own_ppda_5 | −0.00514 | 0.00947 | −0.54 | 0.587 | −0.0256 |
| own_deep_5 | +0.01292 | 0.01488 | 0.87 | 0.385 | +0.0469 |
| faced_ppda_5 | +0.00348 | 0.00888 | 0.39 | 0.695 | +0.0192 |
| faced_deep_5 | +0.01732 | 0.01583 | 1.09 | 0.274 | +0.0476 |
| own_ppda_10 | +0.00664 | 0.01151 | 0.58 | 0.564 | +0.0274 |
| own_deep_10 | +0.01237 | 0.01824 | 0.68 | 0.498 | +0.0411 |
| faced_ppda_10 | −0.00659 | 0.01102 | −0.60 | 0.550 | −0.0318 |
| faced_deep_10 | +0.01030 | 0.01982 | 0.52 | 0.603 | +0.0229 |

**Bundesliga** (n=579)

| Covariata | beta | se | z | p | beta_std |
|---|---|---|---|---|---|
| own_ppda_5 | +0.00744 | 0.00884 | 0.84 | 0.399 | +0.0387 |
| own_deep_5 | +0.00056 | 0.01403 | 0.04 | 0.968 | +0.0022 |
| faced_ppda_5 | +0.01128 | 0.00817 | 1.38 | 0.167 | +0.0666 |
| faced_deep_5 | +0.01441 | 0.01367 | 1.05 | 0.292 | +0.0441 |
| own_ppda_10 | −0.01249 | 0.01097 | −1.14 | 0.255 | −0.0559 |
| own_deep_10 | +0.00326 | 0.01809 | 0.18 | 0.857 | +0.0117 |
| faced_ppda_10 | −0.01311 | 0.01184 | −1.11 | 0.268 | −0.0658 |
| faced_deep_10 | −0.01811 | 0.01778 | −1.02 | 0.308 | −0.0470 |

**Ligue 1** (n=646)

| Covariata | beta | se | z | p | beta_std |
|---|---|---|---|---|---|
| own_ppda_5 | −0.01374 | 0.00985 | −1.40 | 0.163 | −0.0726 |
| own_deep_5 | +0.02349 | 0.01568 | 1.50 | 0.134 | +0.0927 |
| faced_ppda_5 | +0.00803 | 0.00975 | 0.82 | 0.410 | +0.0420 |
| faced_deep_5 | +0.04110 | 0.01618 | 2.54 | **0.0111** | +0.1241 |
| own_ppda_10 | +0.01838 | 0.01214 | 1.51 | 0.130 | +0.0834 |
| own_deep_10 | −0.01067 | 0.01838 | −0.58 | 0.562 | −0.0387 |
| faced_ppda_10 | −0.01326 | 0.01222 | −1.08 | 0.278 | −0.0600 |
| faced_deep_10 | −0.03658 | 0.02083 | −1.76 | 0.0791 | −0.0904 |

**Quanti coefficienti "significativi" ci si aspetterebbe comunque?** Su 40 coefficienti
(8 covariate x 5 leghe) ce ne sono **2** con p<0.05 — esattamente i **2.0** attesi sotto
l'ipotesi nulla; **0** con p<0.01 contro 0.4 attesi; **4** con p<0.10 contro 4.0 attesi.
I due p<0.05 (Serie A `own_ppda_5`, Ligue 1 `faced_deep_5`) sono entrambi su covariate che
cambiano segno fra le leghe.

### 2.5 Ridondanza con `att0_pure` / `def0_pure` (punto 8)

Correlazione a livello **squadra-partita** sul train (una riga per squadra per partita),
Pearson:

| Covariata | Serie A | Premier | La Liga | Bundesliga | Ligue 1 |
|---|---|---|---|---|---|
| `own_deep_10` vs **att0_pure** | +0.688 | +0.768 | +0.797 | **+0.821** | +0.802 |
| `own_deep_5` vs **att0_pure** | +0.617 | +0.713 | +0.729 | +0.756 | +0.737 |
| `faced_ppda_10` vs **att0_pure** | +0.618 | +0.581 | +0.647 | +0.656 | +0.638 |
| `own_ppda_10` vs **att0_pure** | −0.238 | −0.559 | −0.245 | −0.286 | −0.548 |
| `faced_deep_10` vs **def0_pure** | **+0.675** | +0.656 | +0.579 | +0.661 | +0.548 |
| `own_deep_10` vs **def0_pure** | −0.513 | −0.636 | −0.500 | −0.633 | −0.552 |
| `own_ppda_10` vs **def0_pure** | +0.259 | +0.425 | +0.315 | +0.173 | +0.542 |

Le deep completions rolling sono in larga parte **una riespressione della forza d'attacco
che il motore ha gia'** (fino a r = 0.82 con `att0_pure`), e le deep subite lo sono della
difesa (fino a r = 0.68 con `def0_pure`). Il PPDA rolling e' il meno ridondante, ma anche
quello con il rapporto segnale/rumore peggiore. Le correlazioni complete (Spearman
incluso, entrambe le finestre) sono in `audit/data/ppda_residual_test.json`.

**Correzione a una cella della prima stesura:** Serie A `faced_deep_10` vs `def0_pure`
era scritta +0.541; il valore nel JSON e' **+0.675** (n=1447). Tutte le altre 34 celle
della tabella sono state ricontrollate una per una contro
`audit/data/ppda_residual_test.json` e coincidono.

Ridondanza anche **fra** le covariate: la stessa misura a N=5 e N=10 correla |r| = 0.80–0.93
in tutte le leghe (minimo 0.796, Bundesliga `faced_deep`; massimo 0.926, Premier League
`own_deep`), letti dalla matrice di correlazione del campione di fit. La prima stesura
diceva 0.83 come estremo basso: era sbagliato di 0.03. Con 8 covariate
cosi' collineari gli errori standard sono gonfiati per costruzione: anche un effetto reale
piccolo qui uscirebbe non significativo.

### 2.6 Fit aggregato: significativo, ma e' il caso previsto dal punto 9

| Fit | n | LR (8 gdl) | p |
|---|---|---|---|
| aggregato 5 leghe | 3385 | 24.02 | **0.0023** |
| aggregato 5 leghe **con effetti fissi di lega** | 3385 | 24.24 | **0.0021** |

La significativita' aggregata non e' un artefatto del disallineamento di calibrazione fra
leghe: con le dummy di lega resta identica. Ma e' esattamente il caso che la richiesta
chiedeva di smontare. Coerenza di segno fra le 5 leghe:

| Covariata | Segni fra le 5 leghe | Coerente | Leghe significative al 5% |
|---|---|---|---|
| `own_ppda_5` | + e − | **no** | 1 (Serie A) |
| `own_deep_5` | + e − | **no** | 0 |
| `faced_ppda_5` | solo + | si' | 0 (p minimo 0.141) |
| `faced_deep_5` | + e − | **no** | 1 (Ligue 1) |
| `own_ppda_10` | + e − | **no** | 0 |
| `own_deep_10` | + e − | **no** | 0 |
| `faced_ppda_10` | solo − | si' | 0 (p minimo 0.249) |
| `faced_deep_10` | + e − | **no** | 0 |

Sei covariate su otto cambiano segno da una lega all'altra. Le due con segno coerente
(`faced_ppda_5` sempre positivo, `faced_ppda_10` sempre negativo) non sono significative
in nessuna lega, singolarmente. Il motore del risultato aggregato e' `faced_ppda_10`
(p=0.011 aggregato, beta −0.0112), che per lega sta fra p=0.249 e p=0.550: un effetto
coerente in direzione ma troppo piccolo per essere distinguibile dal rumore in qualunque
campionato preso da solo. E' "rumore che si media" nel senso preciso del punto 9: aggregare
moltiplica la potenza senza che nessuna delle 5 evidenze, presa da sola, lo sostenga.

---

## Verdetto

1. **Parte 0 superata, senza punti aperti.** L'archivio PPDA/deep e' popolato con dati
   reali e la copertura coincide con il referto di fattibilita' (7275 completi su 7276, 0
   mancanti, 1 PPDA strutturale); 4 file su 5 sono byte-identici a quelli verificati. Lo
   scheduler settimanale esiste e committa dati + evidenza. Le **224902 righe giocatore
   sono confermate** sull'evidenza committata dal run `35221939505`: 48884 / 47022 /
   49194 / 38910 / 40892, identiche al referto di fattibilita' lega per lega, con 191
   righe in piu' tutte attribuibili a 6 partite di La Liga fuori perimetro (sezione 0.4).
2. **Parte 1 superata.** L'archivio rolling e' point-in-time per costruzione e il test di
   leakage lo conferma a scarto 0 su 125 partite con 2250 partite future iniettate; il test
   cattura una variante volutamente leaky, quindi non e' vacuo.
3. **Parte 2: il segnale non c'e'.** Nessun fit per lega significativo, 2 coefficienti
   significativi su 40 contro 2.0 attesi per caso, 6 covariate su 8 con segno incoerente
   fra leghe, e le feature piu' informative sono gia' dentro `att0_pure`/`def0_pure`
   (r fino a 0.82). La significativita' aggregata esiste ma non sopravvive al criterio
   dichiarato al punto 9.

**Raccomandazione:** chiudere la pista qui, come le 4 precedenti di Astra. Non passare a
validation 2024/25 e backtest 2025/26: con 5 leghe per 8 covariate, un test di validation
su questo effetto avrebbe piu' probabilita' di produrre un falso positivo che di confermare
qualcosa. Se si vuole riaprire, l'unico candidato non scartato dal segno e' il PPDA subito
a finestra 10 (`faced_ppda_10`, negativo in tutte e 5 le leghe), e andrebbe testato da
solo — una covariata, non otto — su un perimetro piu' lungo di 2022/23+, che e' il vero
vincolo di potenza di questo test.

## Che cosa NON e' stato fatto

- nessuna modifica a `app.py`, `config.py`, `models/`, formule, soglie, pesi o
  `PRIOR_MATCHES`; nessun collegamento dei due archivi al motore Poisson/Elo;
- nessun uso di validation 2024/25 o test 2025/26: il fit e' solo sul train, per decisione;
- nessuna imputazione: le partite senza feature rolling restano fuori e sono contate;
- nessuna tolleranza fuzzy sulla data nell'unione dei due archivi;
- i file `player_match_<lega>.json` non sono committati (scelta esplicita, ~91 MB):
  restano nell'artifact del run e nei conteggi dell'evidenza committata.

## Limiti dichiarati

- Understat non pubblica snapshot datati: la disponibilita' reale dei dati al momento della
  partita non e' ricostruibile a posteriori; il test di leakage garantisce che la finestra
  non guarda avanti **dentro questo archivio**, non che l'archivio sia quello che si
  sarebbe visto quel giorno;
- gli xG e le statistiche di Understat possono essere rivisti dopo la partita;
- la finestra rolling non ha tetto di eta': l'1.09% delle finestre N=10 contiene una
  partita piu' vecchia di 400 giorni (massimo 1253 giorni), dichiarato in `*_age_days`;
- le 8 covariate sono fortemente collineari (|r| fino a 0.93 fra N=5 e N=10 della stessa
  misura): il test ha poca potenza per costruzione, e questo e' un limite del test, non
  una prova che l'effetto sia nullo;
- 18 partite su 7279 in comune ai due archivi (0.25%) non si agganciano: 17 per disaccordo di
  data fra Understat e football-data (16 entro 2 giorni, 1 partita rinviata e recuperata a
  −11 giorni) e 1 per campo invertito (Rennes-PSG del 2026-08-23); 6 sono nel train
  (0.17%). Sono elencate e verificate una per una nella sezione 2.2;
- il walk-forward ricostruisce `avg_h`/`avg_a` come medie progressive sullo storico
  disponibile nei CSV (2022/23 in poi), non come le medie sull'intero database che la
  produzione ha oggi in memoria: e' la stessa ricostruzione no-leakage degli audit
  `pt19_age_cap_audit.py` e `pt19_cap_vs_fseason_clean.py`;
- il test e' sul **residuo del totale gol**: dice se le feature rolling spiegano i gol
  totali oltre il lambda attuale, non se migliorerebbero il Brier di Over/Under 2.5 o di
  GG/NG. Questa e' la domanda posta al punto 7; la domanda sul Brier e' quella del passo
  successivo, che questo referto sconsiglia.

## Riproduzione

```bash
# acquisition (GitHub Actions, il sandbox non ha egresso verso Understat)
#   .github/workflows/update_ppda_player.yml — run 35120920395 (dati), 35125626021 (fallito
#   allo step di commit, causa in 0.4) e 35221939505 (evidenza + 3 partite di La Liga)

# copertura ricalcolata in locale sui file committati
python audit/ppda_deep_player_audit.py --database-dir SoccerMath/database \
       --xg-dir SoccerMath/database --datasets ppda_deep --results-dir /tmp/audit_local

# archivio rolling + test di leakage
python audit/build_ppda_deep_rolling.py --leakage-sample 25
python -m pytest audit/test_ppda_deep_rolling.py -q          # 6 passed

# test sul residuo
python audit/ppda_residual_test.py
```

L'evidenza di copertura e' nel repository (commit `2c9edcb`), quindi la riproduzione non
dipende piu' dall'artifact del run, che da questo ambiente non e' scaricabile.

Ambiente della riproduzione: Python 3.11, pandas 3.0.5, numpy 2.4.6, statsmodels 0.15.0,
scipy 1.17.1, streamlit (solo per importare `app.py` in sola lettura); soccerdata 1.9.1 sul
runner (versione verificata per le colonne di `read_team_match_stats()`).
