# Margini migliorabili del selettore Top Mix (e del motore che lo alimenta)

**Esito in una riga: il margine più grande e misurato non è l'ordine del
selettore (già testato e non promosso) ma il filtro `abs(poisson − elo) < 0,25`
usato come *cancellazione della partita*; il margine più grande *strutturale* è
che il Top Mix non è misurabile — tre problemi bloccanti nel registro — e il
backtest dell'app non misura il motore di produzione.**

Documento di analisi. Nessuna formula, soglia, peso, registro o file di
`SoccerMath/` è stato modificato: `git status` mostra solo file nuovi in
`audit/`. I numeri sono rigenerabili con l'harness
[`audit/topmix_margins.py`](topmix_margins.py) (sola lettura) e il loro output
completo è in [`audit/results/topmix_margins.md`](results/topmix_margins.md).

| Pezzo | Dove |
|---|---|
| Harness | `audit/topmix_margins.py` |
| Test dell'harness (33, offline) | `audit/test_topmix_margins.py` |
| Numeri generati | `audit/results/topmix_margins.md` · `.json` |
| Fonte dei dati | `audit/results/topmix_selector_replay_rows.csv` (output di `audit/topmix_selector_replay.py`) |
| Protocollo di riferimento | [`topmix_selector_audit_protocol.md`](topmix_selector_audit_protocol.md) |
| Rapporto del confronto A vs B | [`topmix_selector_replay_report.md`](topmix_selector_replay_report.md) |

> **Etichetta obbligatoria.** 2024/25 e 2025/26 sono **validation storica già
> esaminata** (protocollo §3): sono le stagioni su cui sono già stati scelti
> Poisson a due teste, forma fuori dai totali, `PRIOR_MATCHES=6`, e confermati i
> pesi 0.6/0.4. Quello che segue **non è taratura**: misura il **costo di
> vincoli già esistenti** e segnala incoerenze logiche indipendenti dai dati.
> L'unica via non contaminata per *incassare* un margine predittivo resta la
> conferma prospettica 2026/27, che richiede prima il tracciamento (§7).

---

## 0. Come è stato verificato che i numeri siano gli stessi del replay

L'harness **ricalcola** le headline del report committato e le confronta con
`topmix_selector_replay.json`: **24/24 grandezze coincidono** (candidate 3 422,
A ammesse 1 865, Brier A 0,2312, top 10 A: 740 righe, prob 73,2 %, hit 71,8 %,
Brier 0,2013, mix per mercato, 74 pool, slot medi 10,00). Se una di quelle
grandezze derivasse, §4 di questo documento non sarebbe a confronto con il
replay ma con una reinterpretazione silenziosa di esso. Il controllo è anche un
test (`TestConsistenzaConIlReplayCommittato`).

---

## 1. Tabella sinottica

Classificazione: **B** = bug/incoerenza, si corregge senza toccare formule;
**M** = margine misurato ma non dimostrato (serve prospettiva);
**P** = lavoro di misura, sblocca tutto il resto; **N** = nessun margine
(verificato negativo: non toccare).

| # | Funzione | Difetto | Evidenza | Tipo |
|---|---|---|---|:--:|
| 1 | `fetch_and_calc_top_mix` (app.py:1178–1246) | `abs(poisson−elo) < 0,25` **esclude la partita intera** invece di penalizzarla | replay §2/§3 + `topmix_margins.md` §1, §1a, §4, §4a | M |
| 2 | `fetch_and_calc_top_mix` (1211–1220) | se l'Elo fallisce, `elo_prob = poisson_prob`: soglia 1X2 scende a 0,55, il disaccordo diventa 0, la UI mostra un consenso inesistente, `except:` nudo | codice; §7 del file generato (in replay non accade mai: `elo_available` vero su 3 422/3 422 → rischio non misurabile retrospettivamente) | B |
| 3 | `fetch_and_calc_top_mix` (1177) | `@st.cache_data(ttl=1800)` senza argomenti congela `now`: partite già iniziate restano in top 10 e vengono salvate | `results/topmix_registry_tracking.json → cache_30min` (high) | B |
| 4 | `fetch_and_calc_top_mix` (1185) | `requests.get` **senza `timeout`** dentro una funzione cached: una lega che non risponde congela il calcolo | codice | B |
| 5 | `fetch_and_calc_top_mix` (1245) | `time.sleep(6.5)` per lega (5 leghe → 32 s) dentro il cache-miss | codice | B |
| 6 | `fetch_and_calc_top_mix` | il **gate**, il fallback Elo e la cache non sono coperti da nessun test: l'unico test che esegue la funzione asserisce solo giornata/ordinamento, e non è nella lista pytest del workflow | `audit/test_topmix_next_matchday.py:218` (unico `app.fetch_and_calc_top_mix()` dei 394 test) vs `.github/workflows/topmix_audit.yml` (4 file, non quel file) | B |
| 7 | `save_prediction_entry` (302) | dedup per solo `match_id`: se Analisi Rapida/Billy hanno già salvato, il Top Mix **non viene registrato**; un ricalcolo non aggiorna | `topmix_registry_tracking.json` (3 problemi `blocking`) | P |
| 8 | `save_prediction_entry` (312) | `tipo = "Top Mix" if "Top Mix" in pronostico` | idem | P |
| 9 | `save_predictions` (184–200) + toast (1641) | `PUT` senza leggere `status_code`, `except: pass`, "✅ Top Mix salvati!" non condizionato | idem | P |
| 10 | `registro` (tab5) + `prediction_registry.stats_*` | calcola **solo win rate**; `prob_sicuro` è già persistito | codice | P |
| 11 | `run_historical_backtest` (769) | testa un **altro modello** (`get_full_poisson` a testa singola, Elo proprio senza `margin_mult` né xG) e senza quote/Brier; `models/backtest.py` è importato (35) e mai chiamato | review §1.2, mai eseguito | P |
| 12 | `analisi_rapida_giornata` (1248) vs `show_details` (1280) | dialoghetto: argmax su **5** mercati (manca GG/NG) e `_two_heads_from_lambdas` chiamato **senza** `base_pure_*` (app.py:1319) → testa Totali con la forma, cioè la configurazione misurata come peggiore | `results/form_totali_diagnosis.md` (Brier O/U 0,2488 → 0,2401 senza forma) | B |
| 13 | `calcola_segnali` (1010) | stanchezza infrasettimanale applicata **solo** dentro `show_details`, mai in Top Mix/Analisi Rapida; costanti 0,04/0,05/0,02 mai validate; `stand` e `*args` ignorati | codice | B |
| 14 | `get_league_engine` (750–751) + `config.MARKET_VALUES` (263) | dizionario scritto a mano, non versionato per stagione → **leakage** su ogni valutazione storica, ed è l'unico componente che sposta il ROI | `market_value_comparison.txt` (Poisson val −17,4 % → con mercato −1,5 %) | B |
| 15 | `get_league_engine` (551–569) | forma `tail(5)` sul df multi-stagione (neopromosse: partite di stagioni precedenti), senza split casa/trasferta | `topmix_selector_replay.md` §9 | M |
| 16 | `get_league_engine` (574–589) vs `_league_mean_gate` (457) | stesso gate duplicato (inline "resta intatto per la testa 1X2") | codice | B |
| 17 | `_two_heads_from_lambdas` (941–972) | l'ancora `S = base_h + base_a` **include la forma** mentre la testa Totali usa le lambda pure: le due teste hanno due diverse somma-attesa dei gol, e `argmax` su 7 mercati confronta scale prodotte da due modelli. S alternativa mai testata | nessun audit copre S | M |
| 18 | `blend_elo_into_1x2` (496) + `predict_elo_probs` | pesi ok (0,6/0,4 validato), ma l'Elo che entra nella confidence è **stale**: `_ELO_ENGINES_CACHE` (elo_engine.py:212) senza TTL vs `get_league_engine` cached 3 600 s | codice | B |
| 19 | `EloEngine.compute_ratings` (elo_engine.py:126–134) | `xg_adj` legge lo **snapshot statico** `xg_<lega>.json` (media stagionale) mentre la testa Totali è migrata a `season_point_in_time_averages`; fattori 0,15 e clamp ±100 mai sweepati | `xg_rolling_walkforward_results.txt` (rolling non promove) | M |
| 20 | `predict_elo_probs` (elo_engine.py:242, duplicato in app.py:871) | curva del pareggio fissa `0,27·exp(−(dr/320)²)` clip [0,06,0,34]: governa il mercato più disallineato (`X` 22,1 % dichiarato vs 25,2 % reale) ed è duplicata in due file | `topmix_selector_replay.md` §6 | M |
| 21 | Top Mix come prodotto | `X` non è mai argmax (0/3 422) e non può superare 0,55 → **mercato morto**; `NG` sopravvive solo nominalmente (2 righe su 1 865) | `topmix_margins.md` §6 | B |
| 22 | `aggiorna_risultati_reali` (319–424) | due rami di grading con coperture diverse (`OVER_1.5`, `1X`, `X2`, `12` graduati solo nel ramo `match_id`) + `except: pass` | codice | B |
| 23 | soglie 0,55/0,60 | sotto soglia la frequenza reale è in linea con la dichiarazione: allargare = volume, non valore | `topmix_margins.md` §1b | **N** |
| 24 | ordine A → B | non promove (hit 66,2 % vs 56,8 % sui 74 casi in disaccordo; top 10 indistinguibile) | `topmix_selector_replay_report.md` §2, §4 | **N** |
| 25 | `PRIOR_MATCHES` 6 → 8/10 | zona di equivalenza 6–10, ΔBrier 0,0004 | `prior_matches_audit_report.md` §H | **N** |
| 26 | numero 10 della top 10 | le righe 11–15 fanno hit 56,4 % contro 71,9 %: il taglio è netto | `topmix_margins.md` §4b | **N** |
| 27 | correzione del numero esposto (curva globale o bias per mercato) | trasferita fra stagioni non migliora (ΔBrier +0,0007/+0,0016) o peggiora (+0,0037/+0,0066) | `topmix_margins.md` §5, §5b | **N** |

---

## 2. Il margine «gate» sul selettore (§1–§4 di `results/topmix_margins.md`)

**Cosa fa oggi.** Per ogni partita: argmax Poisson sui 7 mercati → se 1X2,
`confidence = 0,6·Poisson + 0,4·Elo` → doppia verifica `confidence ≥ soglia` **e**
`|poisson − elo| < 0,25`. Se una delle due fallisce, la partita sparisce: nessun
altro mercato viene considerato.

**Quanto costa**, sulle 3 422 partite candidate rianalizzate:

| Scartata per | n | prob dichiarata | hit se accettata | Brier |
|---|---:|---:|---:|---:|
| soglia 0,55/0,60 (solo) | 1 326 | 55,5 % | 57,0 % | 0,2452 |
| **disaccordo Elo ≥ 0,25 (solo)** | **194** | 65,8 % | **64,9 %** | **0,2203** |
| entrambi i vincoli | 37 | 50,7 % | 27,0 % | 0,2640 |

Le ammesse fanno hit 62,0 % e Brier 0,2312: il gate butta via partite **migliori
della media**, la soglia no (è in linea con la propria dichiarazione, quindi
allargarla porterebbe volume e non valore).

Il danno non è uniforme, ed è qui il segnale più interessante:

| Mercato bloccato solo dal gate | n | prob | hit | gap |
|---|---:|---:|---:|---:|
| `1` | 87 | 67,3 % | **73,6 %** | **−6,3 pp** |
| `2` | 107 | 64,6 % | 57,9 % | +6,6 pp |

Sulle vittorie interne il disaccordo Elo **segnala proprio le partite sbagliate
da scartare**: la loro frequenza reale è 6,3 pp *sopra* la probabilità dichiarata.
Sulle vittorie esterne funziona. Il gate, essendo un numero unico applicato a
entrambi i lati, butta via informazione in un caso e rumore nell'altro.

**Sull'oggetto reale (top 10, pool = settimana ISO del cutoff, 74 pool):**

| | righe | prob media | hit | Brier |
|---|---:|---:|---:|---:|
| con il gate (produzione) | 740 | 73,2 % | 71,8 % | 0,2013 |
| senza il gate (stesse soglie) | 740 | 73,8 % | **72,6 %** | **0,1978** |

Cambiano **74 slot su 740** (10 % degli slot riempiti): entrano righe con hit
74,3 % / Brier 0,1846, escono righe con hit 66,2 % / Brier 0,2199 — e sono
**tutte 1X2** (42 volte `1`, 32 volte `2`). Bootstrap a blocchi sul pool
(2 000 draw, seed fisso): **ΔBrier −0,0035 (IC95 % −0,0080…+0,0011)**,
**Δhit +0,8 pp (IC95 % −0,4…+1,9 pp)**.

**Cosa questo non dice.** Non dice «togliere il gate è meglio»: l'intervallo
include lo zero, il confronto non è appaiato (insiemi diversi di partite), e le
due stagioni sono validation riusata. Dice che il gate è l'unico vincolo del
selettore il cui **costo stimato è negativo** e il cui meccanismo è capito, mentre
l'ordine (già testato) non ha mostrato nulla. È il primo candidato per la
conferma prospettica, con una specifica: se il gate diventa *soft*, il blend
0,6/0,4 resta l'unico posto dove il disaccordo agisce — va verificato che non si
trasformi in una fiducia più alta proprio dove i due modelli divergono.

Una terza opzione, intermedia e testabile con lo stesso harness, è **lasciar
vivere la partita ma non mostrare la riga**: oggi un `|Δ| ≥ 0,25` cancella la
partita, e in quelle 194 il secondo mercato (quello che B recuperava) era peggiore
del primo. Il selettore non ha un concetto di «riga ammessa con avvertenza».

---

## 3. La scala della `confidence`: margine reale, non incassabile (§2, §5, §5b)

`confidence` non è una quantità confrontabile fra mercati: 1X2 è una miscela,
totali sono Poisson puro con soglia più alta e disaccordo nullo per costruzione.
La top 10 però **ordina su quel numero**. Il gap medio (prob − hit) per mercato
sulle righe ammesse:

| Mercato | n | gap |
|---|---:|---:|
| GG | 372 | +3,5 pp |
| `1` | 806 | +3,9 pp |
| `2` | 318 | +4,4 pp |
| U2.5 | 235 | +5,6 pp |
| O2.5 | 132 | +7,6 pp |
| NG | 2 | +12,4 pp |

Per confronto, la baseline dei 7 mercati sulle *stesse* candidate prima di ogni
selettore è calibrata (gap ≤ 3,1 pp, `topmix_selector_replay.md` §6): la
disparità di cui sopra nasce dal **selezionare il massimo**, cioè dalla coda.

Ho verificato se la correzione fosse trasferibile, in due modi:

- **bias per mercato** stimato su una stagione e applicato all'altra → scarto
  medio fra stagioni **5,4 pp** (O2.5: +0,8 pp in 2024/25, +16,6 pp in 2025/26);
  riordinare la top 10 con la correzione **peggiora** il Brier (Δ +0,0037 e
  +0,0066, a seconda della direzione);
- **curva isotona globale** (monotona: non tocca l'ordine, solo il numero
  esposto) → ΔBrier +0,0007/+0,0016, cioè **nessun guadagno**: si passa un gap
  di +1,5 pp a uno di segno opposto (sovra-correzione della coda alta).

Quindi: **rendere confrontabili le scale è il lavoro giusto, ma non si fa con
queste due stagioni.** Va fatto (a) stimando una mappa per mercato
sull'intero campione di base dove la densità è reale e non selezionata, e (b)
validato in prospettiva. Il margine che intanto si può cogliere gratis è
esporre in UI la *componente* del numero (Poisson ed Elo sono già calcolati e
salvati nel dizionario `all_preds`) invece di un solo valore che mescola due
scale.

---

## 4. Margini «gratis»: degrado silenzioso e coerenza fra schermate

Nessuno di questi tocca formule o soglie, e ognuno cambia ciò che l'utente
vede o ciò che viene registrato.

1. **Elo che non risponde** (app.py:1211–1220). Oggi `elo_prob = poisson_prob`
   + `except: pass`: la riga 1X2 passa con soglia **0,55** invece di 0,60, il
   filtro di disaccordo è neutralizzato, e la UI mostra `elo == poisson` come
   consenso. Minimo intervento: marcare la riga (`elo_disponibile=False`),
   applicare la soglia dei totali (0,60) perché la confidence è Poisson puro,
   e loggare.
2. **Cache che congela il tempo** (app.py:1177). `fetch_and_calc_top_mix` è
   `@st.cache_data(ttl=1800)` senza argomenti → `now` è fermo per 30 minuti.
   `select_next_matchday_matches` riceve `now` opzionale: basta passare una
   chiave (o rifiltrare al render). È classificato *high* dal report di
   tracciamento.
3. **Rete senza `timeout` + `sleep(6.5)`** (app.py:1185, 1245). Un solo league
   endpoint lento tiene bloccato un calcolo cached e brucia 32 s di coda di
   rate-limit a ogni miss.
4. **Il dialoghetto dice un'altra cosa** (app.py:1290, 1319). Argmax su 5 mercati
   (GG/NG fuori) e `_two_heads_from_lambdas` senza `base_pure_*`: la testa Totali
   del dialoghetto usa la forma a 5 gare, che l'audit ha misurato come
   **migliore da rimuovere** sui totali. Stessa partita → numeri diversi fra
   card, Top Mix e dialogo.
5. **`calcola_segnali` è orfano** (app.py:1010, chiamato solo a 1306–1307):
   il segnale di stanchezza infrasettimanale esiste ma non entra mai nel Top Mix.
   O lo si collega e lo si misura, o si toglie: tenerlo a metà è il costo peggiore
   (un numero che nessuno valida ma che cambia le risposte).
6. **Gradings divergenti** (app.py:319–424): due rami, elenchi di mercati diversi.
   Un record con `OVER_1.5`/`1X`/`X2`/`12` salvato da un percorso diverso dal
   `match_id` diretto resta `⏳` per sempre, silenziosamente.
7. **La guardia esiste ma non guarda il selettore.** `audit/test_reconstruct_topmix_match.py`
   confronta le costanti della trascrizione con l'AST di `app.py`
   (`test_weights_and_thresholds_match_fetch_and_calc_top_mix`: cerca i testi
   letterali `min_conf = 0.55`, `abs(poisson_prob - elo_prob) < 0.25`, `[:10]`)
   e `topmix_audit.yml` la esegue in CI con i requisiti installati: bene, ma è
   un guard **sul testo**, non sul comportamento — e il file che invece esegue la
   funzione con HTTP mockato (`test_topmix_next_matchday.py:218`) **non è** nella
   lista `pytest` del workflow. Conseguenza pratica: il punto 1 di questo elenco
   (fallback Elo) e il gate di §2 vivono nella parte che nessun test eseguito in
   CI tocca; e qualunque correzione del blend dovrà aggiornare anche il guard
   testuale.

---

## 5. Motore e dati: i margini strutturali (non del selettore)

| Funzione | Cosa si può fare | Perché è un margine |
|---|---|---|
| `get_league_engine` + `config.MARKET_VALUES` | versionare i valori per stagione (o escludere il fattore mercato dal giudizio storico) | `market_value_comparison.txt`: con il fattore mercato il ROI 1X2 passa da −17,4 % a −1,5 % in validation. **Tutto il valore misurato dipende da un numero scritto a mano e fermo a una data**, e il replay lo dichiara come leakage (`topmix_selector_replay.md` §9). È il singolo punto dove un dato nuovo (Transfermarkt archiviato per anno) cambia la valutazione di *ogni* leva provata finora |
| `get_league_engine`, forma | forma su sola stagione corrente + split casa/trasferta; la forma a 5 è validata **solo** per la testa 1X2 | il replay dichiara che per una neopromossa le «ultime 5» includono partite di stagioni precedenti |
| `get_league_engine`, `avg_h/avg_a` | media di lega su un solo campione recente (oggi è pooling su 4 stagioni con `peso=1.0`) | `time_decay_diagnosis.md`: il decay per-lega migliora Premier/La Liga/Ligue 1 e peggiora Serie A/Bundesliga → la recency *non* è un guadagno libero, ma il fatto che l'ancora di lega sia multi-stagione non è mai stato un decision point |
| `_two_heads_from_lambdas` | testare l'ancora `S` (forma vs pura) e la coerenza fra teste | le due teste usano somma-attesa dei gol diversa; `argmax` su 7 mercati confronta probabilità di due modelli. Nessun audit misura S |
| `_clip_lambda` (894) | clip superiore `exp(3)` ≈ 20 gol: inerte | il valore utile è solo il lato basso; non è un rischio, è un decorativo |
| `_league_mean_gate` (457) vs gate inline (574–589) | unificare | stesso gate scritto due volte: divergerà |

---

## 6. Elo: il 40 % della confidence mostrata, con i suoi margini

1. `_ELO_ENGINES_CACHE` (elo_engine.py:212) non ha scadenza: in una sessione
   lunga il filtro di disaccordo confronta un Poisson fresco (ttl 3 600) con un
   Elo vecchio. Allineare le due cache è gratis.
2. `xg_adj = ((h_xg − h_xga) − (a_xg − a_xga)) * 0,15` con `xg_elo_boost =
   clamp(±100)` (elo_engine.py:132–136): legge `xg_<lega>.json`, cioè la **media
   stagionale dello snapshot corrente**, non point-in-time. La testa Totali è già
   migrata a `season_point_in_time_averages` (`xg_archive.py:811`): la stessa
   migrazione sull'Elo è il passo naturale, e i due fattori (0,15 e ±100) non
   hanno mai avuto un confronto prima/dopo.
3. `p_draw = 0,27·exp(−(dr/320)²)` clip [0,06,0,34], duplicato in `app.py:871`:
   parametri a mano. È il mercato con il maggiore disallineamento della baseline
   (X −3,1 pp). `draw_correction.py` ha dato esito misto (ROI Premier +10,7 pp,
   Serie A −8,1 pp): nessun verdetto, ma la duplicazione del codice va eliminata
   prima di qualunque esperimento.
4. `run_historical_backtest` usa un **Elo diverso** (K=24 senza `margin_mult` e
   senza xG, app.py:855–875) da `models/elo_engine.py`: il protocollo
   («vietato sostituire in silenzio il motore live con un Elo da backtest
   in-app diverso da `models/elo_engine.py`») lo vieta esplicitamente, eppure il
   tab BACKTEST dell'app lo fa.

---

## 7. Margine P: senza tracciamento non si incassa niente

Da `results/topmix_registry_tracking.json`, tre problemi **blocking** e uno
high, tutti già citati sopra:

- `save_prediction_entry` ritorna subito se il `match_id` è già nel registro →
  il Top Mix non è distinguibile da Analisi Rapida/Billy e non si può misurare
  *in cieco* la sua selezione;
- `tipo` derivato da sottostringa del pronostico → origini collassati;
- campi assenti: `calculation_id`, `origin`, `selector_version`, `rank`,
  `kickoff_utc`, `data_snapshot_sha`, `poisson`, `elo` → senza questi il §5 del
  protocollo non ha oggetto misurabile;
- `save_predictions`: PUT senza `status_code` e `except: pass`, toast non
  condizionato → si può credere di avere un record e non averlo.

Aggiungo un punto non presente in quel referto: **`prob_sicuro` è già salvato**,
quindi una riga di **Brier/affidabilità per mercato** nel tab Registro è
gratuita e darebbe un numero live di calibrazione, che oggi non esiste da
nessuna parte. E l'intervento 6 di §1 (estrarre la selezione in funzione pura)
rende il tracciamento anche testato, non solo registrato.

---

## 8. Anti-margini (dove l'evidenza dice «non toccare»)

| Leva | Verdetto | Fonte |
|---|---|---|
| ordine A → B (confidence su tutti i mercati) | non promove: sui 74 casi in disaccordo A hit 66,2 % vs B 56,8 %; top 10 indistinguibile (ΔBrier +0,0004); le 155 righe in più sono di qualità peggiore e non entrano | `topmix_selector_replay_report.md` §2–§4 |
| soglie 0,55/0,60 | sotto soglia hit in linea con la dichiarazione (57,0 % vs 55,5 %) e lo slot #10 si chiude in media a 66,6 % → volume, non valore | `results/topmix_margins.md` §1b, §4 |
| ricalibrazione del numero esposto | per mercato peggiora, globale non migliora | §5, §5b del file generato |
| `PRIOR_MATCHES` 6→8/10 | ΔBrier 0,0004, zona 6–10 indistinguibile: tenere 6 | `prior_matches_audit_report.md` §H |
| finestra rolling 38 partite | peggiora in 4 leghe su 5; la metrica che l'aveva motivata era **statisticamente scorretta** | `results/lambda_compression_diagnosis.md`, `results/ou_gg_diagnosis.md` (CORREZIONE) |
| xG rolling nell'Elo | misto/negativo (promuove solo Bundesliga) | `xg_rolling_walkforward_results.txt` |
| Dixon-Coles `rho`, time-decay | guadagni sotto il rumore, segno non stabile per lega | `results/dixon_coles_rho_diagnosis.md`, `results/time_decay_diagnosis.md` |
| dimensione 10 della top 10 | 11ª–15ª riga a hit 56,4 % contro 71,9 %: il taglio è dove deve essere | §4b del file generato |
| import di `models/backtest.py` / Dixon-Coles in produzione | `models/backtest.py` non contiene un motore (solo `run_backtest`/`compare_models_backtest`/`detect_value_bets`/metriche, mai chiamate); il motore «più sofisticato» è `models/dixon_coles.py`, che in produzione non gira, e i suoi parametri `xi=0,0019` + `recent_boost=1,3` (righe 92–97) sono due meccanismi di recency sovrapposti e mai disgiunti: prima di discuterne l'ingresso, vanno separati | `soccermath_probability_review.md` §1.1, §1.3, §1.2 |

---

## 9. Piano, nell'ordine in cui lo consiglierei

1. **Tracciamento** (§7): schema §5 del protocollo + dedup per
   `(match_id, origin, selector_version)` + `status_code` verificato + Brier nel
   Registro. Nessun rischio predittivo; senza questo, i passi 2–5 restano
   non verificabili.
2. **Estrazione del selettore** in `seleziona_riga_top_mix(mercati, elo, soglie, pesi)
   -> dict`, chiamata sia da `fetch_and_calc_top_mix` sia dall'harness di audit.
   → **fatto** (salvo la seconda metà: l'harness resta una trascrizione indipendente
   *di proposito*, §11ter).
   Oggi `apply_selector_A` ne è una trascrizione e il solo vincolo fra le due è
   il guard testuale di §4 punto 7: estrarre la funzione lo trasforma in un test
   di comportamento (gate, fallback, argmax sui 7 mercati) eseguibile anche senza
   `streamlit`/`numpy`, cioè dentro l'harness.
3. **Bug gratis** (§4, punti 1–3 e 5–7; §5 ultimo punto; §6 punto 1):
   timeout, cache con `now`, fallback Elo marcato, grading unificato, cache Elo
   allineata, dialoghetto sulle 7 teste con `base_pure_*`. Nessuno di questi può
   «peggiorare il modello»: allineano ciò che l'app dice a ciò che l'app fa. Nello
   stesso passo, una riga in `.github/workflows/topmix_audit.yml`: aggiungere
   `audit/test_topmix_next_matchday.py` (e `audit/test_topmix_margins.py`) alla
   lista di `python -m pytest`, così il corpo del selettore e le tabelle di
   questo referto girano a ogni push su `arena/**`. Non l'ho modificato: è
   fuori dal perimetro «nessun file toccato», ma è il punto col miglior
   rapporto rischio/valore dopo il tracciamento.
4. **Un solo cambiamento predittivo per volta, in prospettiva**: il gate (§2) è
   il candidato con il punto stimato favorevole. Definire *prima* l'esito
   atteso (hit/Brier della top 10 su 2026/27, Δ contro la controparte che resta
   in produzione) e accettare che su 10 giornate il campione sia piccolo: è il
   motivo per cui va fatto in parallelo, non in sostituzione.
5. **`MARKET_VALUES` versionato** (§5): finché non esiste, ogni ROI storico —
   anche quelli citati in questo documento — va letto come *struttura*, non come
   edge.

---

## 10. Cosa questo lavoro NON ha fatto

- Nessuna modifica a `SoccerMath/` (né formule, né soglie 0,55/0,60/0,25, né
  pesi 0,6/0.4, né registro, né JSONBin) e nessuna a `.github/`. Nessun
  `--apply`, nessuna PR.
- Nessuna chiamata di rete, nessuna scrittura nel database, nessuna riga
  aggiunta al registro (verificato dai test di sola lettura).
- Nessuna soglia cercata: le bande sotto soglia in §1b sono **descrizione** del
  taglio esistente, non una proposta di nuovo valore.
- Nessun ricalcolo del motore: l'harness legge il CSV del replay, non riesegue
  Poisson/Elo.

## 11. Limiti

- I candidati vengono dai CSV (nessuno snapshot API TIMED/SCHEDULED);
  `match_id` è la chiave del replay, non l'id football-data.org; `MARKET_VALUES`
  statico applicato a stagioni passate (leakage dichiarato); xG Understat rivisi
  dopo la partita; orari CSV come UTC; forma a 5 sul df multi-stagione; pool
  della top 10 = settimana ISO del cutoff. Valgono identici per ogni confronto
  interno, ma **impediscono di chiamare tutto questo un replay bit-identico del
  Top Mix live** (elenco completo: `topmix_selector_replay.md` §9).
- `elo_available` è `True` su 3 422/3 422 righe e `team_stats_missing` è non
  nullo in 14 partite: l'analisi del §2 non può quindi dirci nulla sul percorso
  di degrado (punto 1 di §4), che resta motivato da lettura del codice.
- 10/384 giornate del replay giravano senza xG point-in-time (2,6 %), tutte la
  1ª giornata: la testa Totali era su fallback-gol solo a campionato appena
  aperto.
- 74 swap su 740 slot su 3 422 partite: la potenza è bassa per costruzione.
- I due file di test che importano `app` (`test_topmix_next_matchday.py`,
  `test_reconstruct_topmix_match.py`) **non sono eseguibili in questo sandbox**
  (manca `streamlit`/`numpy`); i 33 test dell'harness girano invece tutti, perché
  importano solo `csv`/`statistics`. Sono verdi in CI, dove i requisiti sono
  installati e il workflow scatta a ogni push su `arena/**` che tocca
  `SoccerMath/app.py`.

---

## 11bis. Stato dopo il commit di «bug gratis + tracciamento»

Questo referto era diagnostico; il commit successivo ha applicato **solo** la
parte che non tocca formule, soglie o pesi (piano §9 passi 1 e 3, più parte del
passo 2 come copertura di test). Nessuna riga di §2, §3, §5, §6.2, §6.3, §8 è
stata toccata: **il gate, la scala dei mercati, `MARKET_VALUES`, la forma,
l'ancora `S`, la curva del pareggio e l'xG nell'Elo restano esattamente come
erano**, e restano le uniche cose che potevano cambiare il numero predittivo.

| Riga §1 | Cosa è cambiato | Verifica |
|---|---|---|
| 2 — fallback Elo | `elo_disponibile` marcato sulla riga, `except Exception` + `logging.warning`, e **soglia 0,60** quando l'Elo manca (la confidence lì è Poisson puro, non un consenso) | badge `⚠️ Elo n/d · soglia 60%` in UI; ispettore AST `degrado_igiene` |
| 3 — cache 30 min | il TTL **non** è cambiato (passare `now` come argomento = 5 chiamate API/minuto contro il limite free di 10): le righe cached vengono rifiltrate all'uso con `prediction_registry.righe_non_iniziate()` prima di mostrare e di salvare | `audit/test_topmix_registry_tracking.py::TestCacheNonCongelaIlTempo` |
| 4 — GET senza timeout | `timeout=15` sulla GET dei calendari | `requests_get_con_timeout == requests_get_total` |
| 5 — `sleep(6.5)` | la coda ora è **fra** una lega e l'altra (non dopo l'ultima, e non viene saltata dai `continue`) | ispettore AST |
| 6 — copertura test | `.github/workflows/topmix_audit.yml` esegue ora anche `audit/test_topmix_next_matchday.py` (l'unico che **chiama** `fetch_and_calc_top_mix`), `SoccerMath/test_registry_tracking.py` (35 test, solo stdlib) e `audit/test_topmix_margins.py` | la lista `pytest` del workflow + guard `test_i_test_del_selettore_girano_in_ci` |
| 7 — dedup per `match_id` | chiave `(match_id, origin, selector_version)` con `upsert_prediction_entry`: le origini diverse coesistono, un ricalcolo aggiorna la propria riga pending, una riga **gia giudicata non viene mai sovrascritta** | 35 test + `test_standardizza_mercato.py` (aggiornato: il vecchio test asseriva il difetto) |
| 8 — `tipo` dal testo | `origin=` esplicito da tutti e tre i percorsi (Top Mix / Analisi Rapida / Billy); il testo libero resta solo il fallback per i record legacy | `tipo_classification.rule is None` + `origini_esplicite` tutti veri |
| 9 — PUT non verificato | `save_predictions` ritorna `{"locale", "remoto"}`; `status_code` letto; `except Exception` + log; messaggio di tab2 condizionato (`n_err_remoto`) con conteggio nuove/aggiornate/gia giudicate | `jsonbin_write` + `top_mix_success_toast.gated_on_remote_ok` |
| 10 — registro solo win rate | il tab Registro espone **Brier medio, prob. media, gap prob−hit** (`compute_calibration_stats`) e una tabella per **mercato × origine**, più il filtro `Origine`: `prob_sicuro` era già persistito, nessuna migrazione | `registro_ui` + i test sulle statistiche di calibrazione |
| 12 — dialoghetto divergente | argmax su **7** mercati (GG/NG inclusi) e `_two_heads_from_lambdas` riceve le lambda **pure** (`att0_pure`/`def0_pure`), come in produzione | `dialogo_coerente` |
| 16 — gate duplicato | l'inline di `get_league_engine` è sostituito dalla chiamata a `_league_mean_gate()` (una sola soglia di sanità, 0.5–5.0) | `test_get_league_engine_usa_il_gate_condiviso` |
| 18 — cache Elo senza scadenza | `_ELO_ENGINES_STAMP` + `ELO_ENGINE_TTL_SECONDS = 3600`, allineato al `ttl` di `get_league_engine`: il veto sul disaccordo non confronta più un Poisson fresco con un Elo vecchio di ore | `models/elo_engine.py` |
| 22 — grading divergente | i due rami di `aggiorna_risultati_reali` usano la tabella unica `prediction_registry.esito_mercato` (14 mercati, prima il loop per giornata ne conosceva 7) e l'ultimo `except:` muto è diventato un log | `TestGradingUnico` + i casi in `test_registry_tracking.py` |

**Ancora aperti, e perché:**

- **§1 riga 1 (gate) e §3 (scala)**: sono cambiamenti predittivi. Il referto li
  manda in prospettiva 2026/27, non in un ritocco retroattivo sulla validation.
- **§1 riga 11 (backtest in-app) e `models/backtest.py` morto**: richiederebbe
  riscrivere il tab BACKTEST su `models/elo_engine.py` + quote + Brier: lavoro di
  misura, non un bug gratis.
- **§1 righe 13–15, 17, 19–21**: `calcola_segnali` orfano, `MARKET_VALUES`
  statico, forma multi-stagione, ancora `S`, curva del pareggio, xG statico
  nell'Elo, `X`/`NG` mercati morti. Ognuno sposta numeri: vanno decisi uno per
  volta con il protocollo del §5, non infilati in un commit di igiene.
- **Estrazione del selettore** in `seleziona_riga_top_mix()` (piano §9 passo 2):
  **fatta nel passo successivo**, con test di parità bit-per-bit sul corpo
  pre-refactor: §11ter. Rimaneva aperto, fin lì, solo il gate e la scala (§1 riga 1
  e §3), che sono cambiamenti predittivi.

Verifica: **93 test verdi nel sandbox** (quelli che non dipendono da
`streamlit`/`numpy`: 35 + 25 + 33) e **CI verde** su `topmix_audit.yml`
(run `34336124351`) dove i requisiti sono installati — quindi girano anche
`test_topmix_next_matchday.py` (end-to-end su `fetch_and_calc_top_mix` con HTTP
ed Elo mockati), `test_reconstruct_topmix_match.py` (guard letterali sulle
soglie) e `test_standardizza_mercato.py`. Il passo "Nessuna modifica ai
dati/codice di produzione" del workflow è verde: l'audit non ha scritto nel
registro.

Artefatti rigenerati insieme al codice: `audit/results/topmix_registry_tracking.json`
passa da 5 problemi (3 `blocking`) a **0**, con
`can_measure_top_mix_in_isolation: true` (prima era un `False` scritto a mano nel
verdetto: ora è derivato dall'AST, quindi si riaccende da solo se qualcuno
re-introduce uno di quei percorsi).

## 11ter. Stato dopo l'estrazione del selettore (piano §9 passo 2)

Il corpo di `fetch_and_calc_top_mix` è stato diviso in due, senza toccare un numero:

| Pezzo | Righe in `app.py` | Cosa fa |
|---|---|---|
| `seleziona_riga_top_mix(m, elo_probs, elo_disponibile, home, away)` | 1232–1317 | **funzione pura**: i 7 mercati, `best_mkt = max(mercati, key=mercati.get)`, estrazione Elo per `1/X/2`, blend `0,6·Poisson + 0,4·Elo`, `min_conf` 0,60 (totali o Elo assente) / 0,55, veto `|P−E| < 0,25`. Ritorna il dizionario di riga o `None`. Nessun `requests`, nessun `st.`, nessun `logging`, nessun `save_prediction*`, zero `try/except` |
| `fetch_and_calc_top_mix()` | 1321–1383 (decorata `@st.cache_data(ttl=1800)`, invariata) | solo GET con `timeout=15`, motore, `predict_elo_probs` in `try/except` (con `elo_disponibile=False` e log), assemblaggio dei campi del match nell'**identico ordine di chiavi** di prima, `sorted(...)[:10]` e `rank` |

**Come è stato dimostrato che è un refactor.** `SoccerMath/test_topmix_selector_parity.py`
(26 test, **solo stdlib**: gira anche qui, dove `streamlit`/`numpy`/`scipy` non ci
sono) esegue il corpo **PRIMA** e il percorso **DOPO** sugli stessi identici stub
e confronta l'output con `json.dumps` senza `sort_keys`, cioè carattere per
carattere, ordine delle chiavi compreso (che è quello che decide l'ordine delle
colonne del DataFrame in UI):

- il corpo pre-refactor non è una parafrasi: è il **testo del blob**
  `16d4e73:SoccerMath/app.py`, scritto in
  `SoccerMath/test_fixtures/topmix_selettore_pre_refactor.py` da
  `audit/make_topmix_selector_fixture.py` (`--check` rigenera e confronta, così
  il fixture non può essere aggiustato a mano). Il test di provenienza riverifica
  il confronto col blob quando git ha quell'oggetto (CI usa `fetch-depth: 0`);
- **griglia**: 1 400 partite sintetiche a seed fisso, un caso per ogni mercato
  come argmax, un caso su quattro **esattamente** su 0,55 / 0,5499 / 0,60 /
  0,5999, e cinque facce dell'Elo (concorde, in disaccordo, dict senza la chiave
  del mercato scelto, `{}`/`None`, eccezione). Output identico;
- **casi limite**: soglia `>=` sul bordo, `|P−E| = 0,25` esatto (rifiutato) vs
  `0,2499999` (ammesso), soglia dei totali a 0,60 esatta, `Pareggio` e
  `Vittoria {trasferta}` con lo stesso codice mercato, griglia dedicata in cui
  l'Elo manca **sempre** (lì il ramo debole è quello che arriva in top 10);
- **guardie di testo**: ogni riga della matematica di selezione del fixture deve
  riapparire nel nuovo `app.py` o essere elencata in `DICHIARATE` con il motivo
  (le uniche 8 sono l'I/O Elo uscito dal selettore e i tre accessi `elo_p[...]`
  sostituiti da `.get` + controllo sul tipo). Una soglia riscritta fa fallire il
  test: verificato — mutando `min_conf` a 0,56, il gate a 0,35, il peso
  dell'ensemble o invertendo l'ordine delle chiavi, il test di parità **fallisce**.

**Due differenze volute, entrambe non predittive.**

1. `elo_probs` con un valore **non numerico** (es. `"0.70"`): prima propagava un
   `TypeError` fuori dal `try` (l'accesso era fuori dal `try`, che copriva la sola
   chiamata) e perdeva l'intero batch di 5 leghe; ora la riga è marcata
   `elo_disponibile=False` e coincide **riga per riga** con ciò che il selettore
   già fa con l'Elo assente (`test_valore_elo_non_numerico_non_fa_piu_esplodere_il_batch`
   asserisce entrambe le metà).
2. Un `logging.warning("Elo non disponibile…")` in meno quando il dict Elo è
   *presente ma senza la chiave* del mercato scelto: l'informazione ora viaggia
   sul flag della riga, dove il registro la legge davvero. La guardia
   `assert_solo_elo_in_meno` ammette solo questo: nessun avviso nuovo, nessun
   avviso di fetch diverso.

**Guardie ritarrettate (altrimenti la CI era rossa, e per un buon motivo).** Le
soglie non vivono più in una funzione sola, quindi *ogni* guardia che leggeva il
solo `fetch_and_calc_top_mix` è stata estesa al **percorso completo** — se fosse
restata sul chiamante, bastava spostare una soglia per metterla fuori portata:

- `audit/test_reconstruct_topmix_match.py::_app_topmix_source()` → unisce
  `fetch_and_calc_top_mix` + `seleziona_riga_top_mix` (la trascrizione
  `apply_selector_A` resta **indipendente di proposito**: è il confronto esterno
  che tiene in vita la coerenza 24/24 di §0, non va saldata al codice di produzione);
- `audit/inspect_topmix_registry.py`: `top_mix_selector` e `degrado_igiene`
  calcolati sul testo combinato; `_chiave_poisson` accetta `m_poisson["1"]` *o*
  `m["1"]` (ciò che conta è che l'1X2 resti agganciato al vettore a due teste,
  non il nome della variabile);
- `SoccerMath/test_standardizza_mercato.py::test_fetch_and_calc_stores_mercato_standard`
  → `mercato_standard` verificato sull'orchestratore, `codice_mercato_selezionato`
  sul percorso (con la normalizzazione degli apici di `ast.unparse`);
- `audit/test_topmix_registry_tracking.py`: nuova classe `TestSelettorePuro` sui
  fatti `selettore_puro` / `selezione_in_un_solo_punto` / `codice_mercato_chiamato`
  dell'ispettore, **compreso il test che spara**: su due sorgenti mutati in una
  copia temporanea (un `time.sleep` dentro la funzione pura; un secondo
  `mercati = {` nel chiamante) le guardie scattano e `tracking_verdict` riporta
  `selettore_non_piu_puro` (`medium`) e `selezione_duplicata` (`high`). Il codice
  vero resta a 0 problemi.

**CI.** `SoccerMath/test_topmix_selector_parity.py` è stato aggiunto alla lista
`pytest` di `topmix_audit.yml` (e ai suoi `paths:`), quindi la parità è verificata
a ogni push su `arena/**` insieme al resto. L'ordine consigliato del §9 resta
invariato: passo 4 (gate in prospettiva) e passo 5 (`MARKET_VALUES` versionato)
sono ancora aperti.

Verifica di questo passo: **227 test verdi nel sandbox** — 26 parità + 27
guardie tracciamento + 35 registro + 33 harness margini + 16
`test_prediction_registry` + 36 pre-shrinkage + 54 race condition — e **CI verde**
su `topmix_audit.yml` (run `34358112737`, 57 s, `conclusion: success`): lì il
passo «Test diagnostici» esegue **171 test in 8 file**, quindi girano anche i tre
che esigono l'ambiente completo (`test_topmix_next_matchday.py` 8,
`test_reconstruct_topmix_match.py` 20, `test_standardizza_mercato.py` 21) e il
check «Nessuna modifica ai dati/codice di produzione» resta verde.

Artefatto rigenerato: `audit/results/topmix_registry_tracking.json` (0 problemi,
`can_measure_top_mix_in_isolation: true`), nuove chiavi `facts.selettore_puro` e
due chiavi in `facts.top_mix_selector`; nessuna delle chiavi preesistenti cambia
valore. Comando (identico al passo CI, `git diff --exit-code -- SoccerMath
audit/results` che chiude il workflow verifica che sia aggiornata):

```
python - <<'PY'
import json, sys
sys.path.insert(0, "audit")
from inspect_topmix_registry import tracking_verdict, inspect_registry_module
v = tracking_verdict()
src = v["facts"]["dedup_by_match_id"].get("source")
v["facts"]["dedup_by_match_id"]["source"] = src[:400] if src else src
v["registry_module"] = inspect_registry_module()
with open("audit/results/topmix_registry_tracking.json", "w", encoding="utf-8") as f:
    json.dump(v, f, ensure_ascii=False, indent=2); f.write("\n")
PY
```

## 11quater. Gate shadow: il veto come penalità continua (piano §9 punto 4, modalità ombra)

**Cosa è stato aggiunto, in una riga.** Il gate `|P−E| < 0.25` non è stato
toccato: è stata aggiunta una modalità *ombra* che, al posto di scartare la
partita, applica alla confidence una **penalità moltiplicativa continua** e
persiste i due campi `gate_shadow_confidence` / `gate_shadow_ammessa` sulle
righe che la produzione gioca. Nessun cambio a cosa la produzione
mostra/gioca: soglie, pesi, veto e parità di 32e3eda restano intatti
(`test_topmix_selector_parity.py` passa identico).

**Definizione esatta della penalità.** Per ogni candidate il selettore reale
calcola `confidence` (blend 0.6·Poisson + 0.4·Elo per 1X2, Poisson puro per i
totali) e `d = |poisson_prob − elo_prob|` (zero per i mercati senza Elo, dove
l'Elo non viene letto). La variante ombra sostituisce il veto con

```
conf_shadow = confidence · 0.25 / (0.25 + d)        g(d) = 0.25/(0.25+d)
ammessa_shadow = (conf_shadow >= min_conf)          min_conf = 0.55 (1X2 con Elo) / 0.60
```

Proprietà, tutte volute e verificate da `SoccerMath/test_topmix_shadow_gate.py`:

- **continua e senza un secondo taglio secco**: `g` è monotona decrescente in
  `d`, vale 1 a `d = 0`, **1/2 esattamente a `d = 0.25`** (il punto in cui oggi
  la produzione passa da esposizione piena a zero) e tende a 0 senza mai
  azzerarsi per `d` finito. I due filtri di oggi (soglia di qualità **e** veto
  di disaccordo) collassano in un solo confronto `conf_shadow >= min_conf`;
- **mai negativa e senza clamp**: la forma moltiplicativa resta in (0, 1] per
  ogni `d`, a differenza di una penalità sottrattiva `conf − k·d`, che per
  `d ≥ conf/k` richiederebbe di troncare a zero — cioè *un secondo taglio secco
  a un'altra soglia*, la cosa che la modalità ombra deve evitare;
- **ancorata all'unica scala di disaccordo esistente** (la tolleranza 0.25 del
  veto): non introduce nessun iperparametro nuovo, e il suo punto di flesso è
  esattamente il confine del comportamento attuale;
- per i totali / l'1X2 a Elo assente `d = 0` per costruzione: `conf_shadow =
  confidence`, l'ombra non tocca ciò che oggi è già Poisson puro.

**Dove vive e come viene salvata.** La formula è implementata **una sola
volta**, in `prediction_registry.gate_shadow_confidence` (modulo senza
dipendenze: la importano `app.py`, i test e l'harness). Accanto al selettore
c'è `app.riga_top_mix_shadow(...)`, copia speculare *pura* della sola
matematica di selezione (stessa argmax, stesso blend, stesse soglie — mai il
veto), che ritorna sempre un dict con `conf_shadow`, `ammessa_shadow`,
`disaccordo` e `gate_avrebbe_scartato`: serve ai test sugli stessi fixture
della parità e agli strumenti di audit, **non è usata dal percorso live**.
La specularità è tenuta viva da un test di coerenza: sulla griglia sintetica
della parità, quando `seleziona_riga_top_mix` ammette la riga, il lato reale
della mirror coincide con l'output del selettore.

Nel registro i due campi sono **opzionali e puramente aggiuntivi**: il Top Mix
li calcola al momento del salvataggio dai valori della riga
(`gate_shadow_fields_from_row`, cosicché il valore persistito è riproducibile
dal solo record; le componenti `poisson`/`elo` sono arrotondate allo 0.1 pp dal
selettore, quindi `conf_shadow` coincide con l'esatto a meno di ~0.005).
`save_prediction_entry` li scrive **solo** quando `gate_shadow_confidence`
non è `None`: se il calcolo manca o fallisce, il record è bit-identico a
prima (test `TestSalvataggioBitIdentico`). Market, prob, prob_val, rank,
ammissione reale e chiave di dedup non cambiano.

**Cosa misura davvero (e un limite strutturale).** Sulle righe che la
produzione GIOCA, `gate_shadow_confidence` è la fiducia che esporrebbe il
selettore ombra e `gate_shadow_ammessa` dice se quella riga **sarebbe comunque
stata giocata** sotto il solo filtro soft: le righe "fragili" (ammesse oggi,
bocciate dall'ombra) sono il campione appaiato su cui confrontare in cieco
Brier/hit di `conf` vs `conf_shadow` sul 2026/27. Le candidate che il veto
**blocca** oggi non generano riga e non arrivano al registro: loggarle live
richiederebbe di farle uscire da `fetch_and_calc_top_mix`, il cui output è
congelato dalla parità bit-per-bit (una chiave o riga in più farebbe fallire
`test_topmix_selector_parity.py`, e la funzione pura non può scrivere). Per
le 194 bloccate la misura resta quindi harness/ex-post
(`audit/topmix_shadow_gate.py`, tabelle sotto), non registro live.

**Proprietà algebrica da non fraintendere.** Poiché per `d ≥ 0.25` il fattore
vale ≤ 1/2, `conf_shadow ≤ conf/2`; e siccome per essere giocata una 1X2 deve
avere `conf ≥ 0.55`, ogni riga bloccata dal gate ha `conf_shadow ≤ 0.5 <
0.55`: **la variante ombra non riammette mai una riga che il veto blocca**
(sul validation: max `conf_shadow` = 41.2% sulle 194). Questa penalità non
testa "togliere il veto" (quella è la riga "senza gate" di `topmix_margins.md`
§4, che riammetteva 74 slot): testa un selettore **più severo del reale
vicino al confine**, dove il disaccordo scende *in modo continuo* invece che
con un gradino. Il valore della misura non sta nella riammissione, ma nella
scala continua `conf_shadow` e nel confronto appaiato robuste-vs-fragili.

**Numeri sulla validation (rigenerabili, non una taratura).** Sui 3 422
candidate di `topmix_selector_replay_rows.csv` (stesse stagioni già esaminate,
protocollo §3: nessuna conclusione predittiva, solo direzione):

| gruppo | n | prob media | conf_shadow media | d medio | hit | Brier |
|---|---:|---:|---:|---:|---:|---:|
| tutte le ammesse | 1 865 | 66.4% | 54.3% | 0.071 | 62.0% | 0.2312 |
| robuste (ammesse anche dall'ombra) | 1 029 | 66.7% | 63.5% | 0.013 | 62.5% | 0.2298 |
| fragili (oggi giocate, non dall'ombra) | 836 | 66.0% | 42.8% | 0.143 | 61.4% | 0.2329 |
| bloccate dal gate (194, solo harness) | 194 | 65.8% | 29.9% (max 41.2%) | 0.304 | 64.9% | 0.2203 |

Robuste e fragili hanno hit/Brier vicini su validation riusata: **nessun
margine dimostrato** — è esattamente ciò che il confronto in cieco sul
2026/27 (reso possibile dai campi nel registro) deve dirimere. Le fragili
sono tutte 1X2 (548 `1`, 288 `2`), come atteso: i totali hanno `d = 0`.

**Verifica.** `SoccerMath/test_topmix_shadow_gate.py` (aggiunto alla lista
pytest di `topmix_audit.yml`): 23 test — formula esatta su valori noti,
monotonia/continuità/assenza di secondo taglio, casi noti della parità letti
in chiave ombra (veto esatto 0.25 dimezza; appena sotto il veto il selettore
ammette e l'ombra no), coerenza mirror↔selettore su 600 casi, salvataggio
bit-identico con e senza i campi (i due test che importano `app.py` girano in
CI, dove le dipendenze ci sono). Parità di 32e3eda e guardie di tracciamento:
intatte. Nel venv completo la lista CI di §11ter più il nuovo file fa **194
test verdi**; nel sandbox ridotto i 2 test che importano `app.py` (streamlit)
vengono saltati, gli altri 21 girano con la sola stdlib.

## 11quinquies. Gate off: il veto assente, modalità ombra (secondo segnale, parallelo a §11quater)

**Cosa è stato aggiunto, in una riga.** Accanto alla penalità continua di
§11quater vive un **secondo** segnale ombra, indipendente, che simula il gate
**assente**: nessuno sconto sulla confidence, ammissione = `conf >= min_conf`.
I campi `gate_shadow_confidence` / `gate_shadow_ammessa` e la formula
`conf · 0.25 / (0.25 + d)` **non sono stati toccati**. Nessun cambio a cosa la
produzione mostra/gioca.

**Perché un secondo segnale e non un parametro del primo.** Le due domande
non possono condividere una formula. Il primo segnale (dimezza a `d = 0.25`)
risponde a: *tra le ammesse, quelle vicino al bordo sono più fragili?* Il
secondo risponde alla domanda originale di §2: *il gate scarta partite che in
realtà erano buone?* Verificato sui dati: a un `d_half` che farebbe rientrare
una quota sensata delle 194 bloccate, il primo segnale perde quasi tutto il
potere distintivo sulle ammesse. Due formule, due campi, due confronti in
cieco sul 2026/27.

**Definizione esatta.** Zero parametri liberi:

```
conf_off = confidence                         (identità: nessuno sconto)
ammessa_off = (conf_off >= min_conf)          min_conf = 0.55 (1X2 con Elo) / 0.60
```

`confidence` è già quella calcolata (blend 0.6·Poisson + 0.4·Elo per 1X2,
Poisson puro per i totali). Il disaccordo `d` entra in firma per simmetria
con `gate_shadow_confidence` e viene **ignorato**. Conseguenza: la
popolazione riammessa coincide esattamente con le 194 storicamente scartate
dal solo veto (`A_conf >= min_conf` e `d >= 0.25`) già misurate in
`topmix_margins.md` §2 — è il controllo di coerenza, non un risultato nuovo.

**Dove vive e come viene salvata.** Formula unica in
`prediction_registry.gate_off_confidence`. `app.riga_top_mix_shadow` calcola
anche `conf_off` / `ammessa_off` (stessa funzione speculare, mai nel percorso
live). Nel registro i due campi `gate_off_confidence` / `gate_off_ammessa`
sono opzionali e puramente aggiuntivi, stesso pattern del primo segnale:
`save_prediction_entry` li scrive **solo** se `gate_off_confidence` non è
`None`; i chiamanti che non li passano producono un record bit-identico.
Solo il salvataggio Top Mix live li passa, calcolati da
`gate_off_fields_from_row` sui valori della riga.

**Limite strutturale (identico a §11quater).** Le 194 bloccate non arrivano
al registro live: la misura su di esse resta harness/ex-post
(`audit/topmix_shadow_gate.py`). Sulle righe giocate il campo `ammessa_off`
è sempre `True` (sono ammesse, quindi `conf >= min_conf`): il valore
prospettico del secondo segnale sta nel confronto *se il veto fosse stato
assente* sulle candidate che il live non mostra, non nel frazionare le
ammesse.

**Numeri sulla validation (rigenerabili, non una taratura).** Sulle 194
bloccate dal solo gate (`topmix_selector_replay_rows.csv`):

| gruppo | n | conf_off media | riammesse da gate_off |
|---|---:|---:|---:|
| bloccate dal gate (solo harness) | 194 | 65.8% | **194** (per costruzione) |

Hit se accettate 64.9%, Brier 0.2203: identici a `topmix_margins.md` §2,
perché `conf_off == A_conf`. Il primo segnale, sulle stesse 194, riammette
**0** (max `conf_shadow` 41.2%). Le due colonne nel registro renderanno il
confronto misurabile in cieco sul 2026/27, una domanda per volta.

**Verifica.** Stesso file `SoccerMath/test_topmix_shadow_gate.py`:
`gate_off_confidence(c, d) == c` per qualunque `d`; indipendenza dal primo
segnale (a `d = 0.25` il primo dimezza, il secondo resta); campi da riga
riammettono la bloccata e bocciano sotto soglia; salvataggio bit-identico
con e senza i nuovi campi (e i campi del primo segnale restano assenti se
non passati). Parità di 32e3eda e §11quater: intatte.

## 12. Riproduzione

```bash
python audit/topmix_margins.py            # scrive audit/results/topmix_margins.{md,json}
python audit/test_topmix_margins.py       # 33 test, offline
python -m pytest audit/test_topmix_margins.py -q   # equivalente, se pytest è installato

# gate shadow (§11quater) + gate off (§11quinquies): due segnali paralleli
python audit/topmix_shadow_gate.py        # scrive audit/results/topmix_shadow_gate.{md,json}
python -m pytest SoccerMath/test_topmix_shadow_gate.py -q   # formula, mirror, salvataggio bit-identico (2 richiedono l'ambiente completo)

# per rigenerare anche la fonte:
python audit/topmix_selector_replay.py --out audit/results    # ~2 min

# parità del selettore dopo l'estrazione in funzione pura (§11ter) — solo stdlib:
python SoccerMath/test_topmix_selector_parity.py                     # 26 test
python audit/make_topmix_selector_fixture.py --check                # fixture == blob git
# (senza --check rigenera il fixture: si fa solo se `app.py` di ORIGINE cambia, cioè mai)
```
