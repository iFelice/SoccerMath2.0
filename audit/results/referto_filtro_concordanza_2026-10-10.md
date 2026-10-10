# Referto di audit — filtro di concordanza sulle scelte di mercato + follow-up PR #61 (punti A, B, C)

Branch `arena/0dbf3f5a-soccermath2-0`, base `f7b224d` (PR #61 già mergiata). Data: 2026-10-10.

Vincoli rispettati: nessuna modifica a `SoccerMath/` né a `SoccerMath/app.py`; nessun
replay con `--write`; nessuna chiamata a The Odds API; nessuna chiave in alcun file, log
o output; nessuna scrittura nel Registro; nessun download da `football-data.co.uk`.
**La PR resta aperta: non fare merge.**

Il referto contiene, in ordine: il referto integrale dell'ipotesi del filtro (con la
REGOLA DICHIARATA scritta prima dei numeri e mai modificata dopo), i punti aggiuntivi A
(eventi già iniziati nella sonda totals), B (test saltati) e C (replica del de-vig), e la
chiusura con gli output reali di suite, CI e replay più l'elenco di ciò che non è stato
verificato.

---

# Filtro di concordanza sulle scelte di mercato (`topmix_mercato_v3`)

## Regola dichiarata (prima dei numeri; questa sezione non viene modificata dopo)

**Campione.** Le 1.302 scelte di mercato del replay `topmix_mercato_v3` (PR #49),
ciascuna con probabilità di mercato `p_m` dell'esito scelto e probabilità del
modello Drago `p_d` per lo stesso esito, walk-forward come in produzione
(blend 0,25 Poisson + 0,75 Elo, colonne `m0/m1/m2` del frame della PR #49).
Scarto = `p_d − p_m`. Il replay deve stare in parità con la PR #49
(1302 / 1144 / 335, Δn = 0) prima di ogni numero di questo referto.

**Filtro proposto.** Una scelta passa se `p_m ≥ 0,75` **oppure** `|scarto| ≤ 0,05`.
Soglie fisse: nessuna ricerca di soglie alternative, in nessuna direzione.

**Gruppi.**
- "passa" ed "esclusa" sono calcolati sulle sole scelte con `p_m < 0,75`
  (così il confronto è a parità di probabilità di mercato e il criterio
  sotto test è quello di concordanza): "passa" = `|scarto| ≤ 0,05`,
  "esclusa" = `|scarto| > 0,05`.
- Le escluse si dividono in "modello più alto" (scarto > +0,05) e
  "modello più basso" (scarto < −0,05).
- Il filtro intero in produzione manterrebbe anche le scelte con `p_m ≥ 0,75`
  (passano per definizione): l'esito della regola è riportato anche con
  "passa" esteso a tutte le scelte mantenute dal filtro, come sola sensibilità.
  Il verdetto segue la definizione principale (solo `p_m < 0,75`).

**Incertezza.** Bootstrap a blocchi lega × stagione × data, 2.000 repliche con
reimmissione, IC 95% percentile, seme fisso. `f − p_m` = frequenza di vincita
del gruppo meno la `p_m` media dello stesso gruppo (con segno). La differenza
fra due gruppi è appaiata: gli stessi draw di blocchi valutano entrambi.

**Filtro di concordanza — regola di decisione.** Il filtro si propone per la
produzione solo se valgono entrambe:

- **(a)** nel gruppo "esclusa" l'IC 95% di `f − p_m` è tutto sotto zero;
- **(b)** l'IC 95% della differenza (`f − p_m` del gruppo "passa") −
  (`f − p_m` del gruppo "esclusa") è tutto sopra zero.

In ogni altro caso il filtro non si adotta e lo scarto resta un'informazione
di contesto.

Le tabelle su fasce di `p_m`, regressione logistica e incrocio con la colonna
"d'accordo" sono di contesto: non entrano nella regola. Le soglie 0,75 / 0,05
e i bordi delle fasce non vengono toccati dopo aver visto i dati.

Generato da `audit/filtro_concordanza_scarto.py` il 2026-10-10T21:59:25Z (commit `f7b224d`, branch `arena/0dbf3f5a-soccermath2-0`). Bootstrap: 2000 repliche a blocchi lega × stagione × data, seme 20261010. Nessuna rete, nessuna modifica a `SoccerMath/`.

Replay di provenienza in parità con la PR #49: **SÌ** (1302 scelte di mercato su 3504 righe di campione; max scarto de-vig vs colonne `pre*` PR #49: 1.11e-16).

## 1. Gruppi passa / esclusa (solo scelte con p_m < 0,75)

| gruppo | n | p_m media | frequenza di vincita f | f − p_m | IC 95% a blocchi |
|---|---:|---:|---:|---:|---|
| passa (|scarto| ≤ 0,05) | 561 | 63,31 % | 64,88 % | 1,58 pt | [-2,36 pt; 5,39 pt] |
| esclusa (|scarto| > 0,05) | 555 | 63,28 % | 64,50 % | 1,22 pt | [-2,51 pt; 5,02 pt] |
| esclusa — modello più alto (scarto > +0,05) | 385 | 63,81 % | 63,64 % | -0,18 pt | [-4,66 pt; 4,47 pt] |
| esclusa — modello più basso (scarto < −0,05) | 170 | 62,08 % | 66,47 % | 4,39 pt | [-2,71 pt; 11,39 pt] |

Informazione (fuori regola): le scelte con `p_m ≥ 0,75` passano per definizione: n = 186, p_m media 79,64 %, f = 84,41 %, f − p_m = 4,77 pt [-0,41 pt; 9,56 pt].

## 2. Stessa tabella dentro le fasce di p_m

| fascia | gruppo | n | p_m media | f | f − p_m | IC 95% a blocchi |
|---|---|---:|---:|---:|---:|---|
| [0,55-0,60) | passa (|scarto| ≤ 0,05) | 199 | 57,30 % | 56,28 % | -1,02 pt | [-7,84 pt; 5,79 pt] |
| [0,55-0,60) | esclusa (|scarto| > 0,05) | 189 | 57,26 % | 58,73 % | 1,47 pt | [-5,04 pt; 8,07 pt] |
| [0,55-0,60) | esclusa — modello più alto (scarto > +0,05) | 112 | 57,31 % | 57,14 % | -0,17 pt | [-8,78 pt; 8,88 pt] |
| [0,55-0,60) | esclusa — modello più basso (scarto < −0,05) | 77 | 57,18 % | 61,04 % | 3,86 pt | [-6,88 pt; 14,24 pt] |
| [0,60-0,65) | passa (|scarto| ≤ 0,05) | 143 | 62,20 % | 60,14 % | -2,06 pt | [-10,21 pt; 6,32 pt] |
| [0,60-0,65) | esclusa (|scarto| > 0,05) | 149 | 62,08 % | 59,06 % | -3,02 pt | [-10,94 pt; 4,75 pt] |
| [0,60-0,65) | esclusa — modello più alto (scarto > +0,05) | 111 | 62,13 % | 56,76 % | -5,37 pt | [-14,79 pt; 3,93 pt] |
| [0,60-0,65) | esclusa — modello più basso (scarto < −0,05) | 38 | 61,93 % | 65,79 % | 3,86 pt | [-11,65 pt; 19,17 pt] |
| [0,65-0,75) | passa (|scarto| ≤ 0,05) | 219 | 69,49 % | 75,80 % | 6,31 pt | [0,57 pt; 11,94 pt] |
| [0,65-0,75) | esclusa (|scarto| > 0,05) | 217 | 69,36 % | 73,27 % | 3,91 pt | [-1,91 pt; 9,32 pt] |
| [0,65-0,75) | esclusa — modello più alto (scarto > +0,05) | 162 | 69,46 % | 72,84 % | 3,38 pt | [-3,34 pt; 10,16 pt] |
| [0,65-0,75) | esclusa — modello più basso (scarto < −0,05) | 55 | 69,05 % | 74,55 % | 5,50 pt | [-7,11 pt; 16,47 pt] |

## 3. Regressione logistica dell'esito (1 = vinta)

Modello A: `logit P(vinta) = b0 + b1 · logit(p_m) + b2 · scarto`. Modello B: scarto diviso in parte positiva `max(scarto, 0)` e parte negativa `min(scarto, 0)`. IC 95% dallo stesso bootstrap a blocchi.

| modello | coefficiente | stima | IC 95% a blocchi | repliche valide |
|---|---|---:|---|---:|
| A: y ~ logit(p_m) + scarto | b0 (costante) | -0,1259 | [-0,3696; 0,1088] | 2000 |
| A: y ~ logit(p_m) + scarto | b1 logit(p_m) | 1,4068 | [1,0556; 1,8127] | 2000 |
| A: y ~ logit(p_m) + scarto | b2 scarto | -1,4816 | [-3,3829; 0,1991] | 2000 |
| B: y ~ logit(p_m) + scarto⁺ + scarto⁻ | b0 (costante) | -0,2085 | [-0,5137; 0,0854] | 2000 |
| B: y ~ logit(p_m) + scarto⁺ + scarto⁻ | b1 logit(p_m) | 1,4231 | [1,0673; 1,8326] | 2000 |
| B: y ~ logit(p_m) + scarto⁺ + scarto⁻ | b2 scarto positivo max(s,0) | -0,3908 | [-3,4404; 2,6608] | 2000 |
| B: y ~ logit(p_m) + scarto⁺ + scarto⁻ | b3 scarto negativo min(s,0) | -3,2049 | [-7,4738; 0,5525] | 2000 |

## 4. Incrocio con la colonna "d'accordo" di produzione

Colonna `accordo` del selettore di produzione: modello e mercato sullo stesso esito ed entrambi ≥ 0,55 (`market_odds.SOGLIA_ACCORDO`).

| gruppo | n | p_m media | f | f − p_m | IC 95% a blocchi |
|---|---:|---:|---:|---:|---|
| escluse già "senza accordo" (accordo = False) | 111 | 59,02 % | 63,06 % | 4,04 pt | [-4,69 pt; 12,54 pt] |
| escluse "d'accordo" (accordo = True) | 444 | 64,35 % | 64,86 % | 0,52 pt | [-3,57 pt; 4,88 pt] |
| tutte le escluse | 555 | 63,28 % | 64,50 % | 1,22 pt | [-2,51 pt; 5,02 pt] |

Delle 555 escluse, **111** hanno già la colonna "d'accordo" a False (il filtro non aggiungerebbe nulla su queste) e **444** sono "d'accordo": il loro f − p_m è quello della seconda riga.

## 5. Hit rate prima e dopo il filtro (solo descrittivo)

| insieme | n | vinte | hit rate |
|---|---:|---:|---:|
| insieme completo (scelte di mercato) | 1302 | 879 | 67,51 % |
| dopo il filtro (solo scelte che passano) | 747 | 521 | 69,75 % |
| scelte perse (escluse) | 555 | 358 | 64,50 % |

Scelte perse dal filtro: **555** (hit rate 64,50 %).

## 6. Esito della regola (a)(b)

| condizione | misura | IC 95% a blocchi | esito |
|---|---|---|---|
| (a) IC 95% di f − p_m del gruppo "esclusa" tutto sotto zero | f − p_m = 1,22 pt | [-2,51 pt; 5,02 pt] | NON SUPERATA |
| (b) IC 95% di (f − p_m)passa − (f − p_m)esclusa tutto sopra zero | differenza = 0,36 pt | [-5,20 pt; 6,11 pt] | NON SUPERATA |

**Verdetto: IL FILTRO NON SI ADOTTA** — non valgono (a) e (b): lo scarto resta un'informazione di contesto, come da regola dichiarata.

Sensibilità (gruppo "passa" esteso a tutte le scelte mantenute dal filtro, incluse `p_m ≥ 0,75`): differenza (f − p_m) = 1,15 pt [-3,93 pt; 6,04 pt]; condizione (b) non superata anche in questa lettura. Il verdetto resta quello della definizione principale.

## 7. Limiti dichiarati

- Le stagioni 2024/25 e 2025/26 sono già state usate dal progetto: l'ipotesi del filtro è nuova, ma i dati non sono vergini. L'ipotesi è stata formulata dopo aver visto più volte queste stagioni.
- Le probabilità di mercato vengono dai CSV storici B365 pre-chiusura de-vigati proporzionalmente (fonte del replay della PR #49), non dalle quote live di produzione.
- Lo scarto p_d − p_m è calcolato sullo stesso esito scelto dal mercato: non è uno scarto medio sulle tre vie.
- I bootstrap a blocchi lega × stagione × data tengono conto della correlazione entro la stessa giornata di lega; non delle altre dipendenze (formazioni, mercati comuni).
- La regressione logistica è associativa: il coefficiente dello scarto non identifica un effetto causale del modello.
- Colonna "d'accordo": definizione di produzione (stesso esito, entrambi ≥ 0,55). Nessuna soglia alternativa è stata cercata.
- Nessuna modifica a SoccerMath/ né a app.py; nessun --write; nessuna chiamata a The Odds API.


---

## 2. Punto A — eventi già iniziati nella sonda totals

Il referto della PR #61 riportava che per Manchester United–Tottenham lo snapshot totals
del 10/10 (chiamata 17:03:43Z) è successivo al calcio d'inizio (16:30Z): lo snapshot era
contaminato da eventi già iniziati.

### 2.1 Script di analisi della seconda sonda (`audit/totals_probe_seconda_analisi.py`)

- **Esclusione come in produzione 1X2** (`update_live_odds.normalizza_eventi`): ogni
  evento con `commence_time` ≤ istante della chiamata è una partita già iniziata, viene
  escluso e contato (`n_iniziati_esclusi`, il testo della produzione è
  «eventi_iniziati_esclusi»). Il referto della seconda sonda riporta la riga
  «Eventi già iniziati alla chiamata (`commence_time` ≤ istante della chiamata): **N** —
  esclusi dall'analisi, come nella produzione delle quote 1X2». La finestra della regola è
  ora `0 < kickoff − chiamata ≤ 7 giorni` (prima includeva anche il bordo 0).
- **La regola (a)(b)(c) già dichiarata si applica solo agli eventi non iniziati.** Le
  soglie della regola non cambiano (85 % di copertura; concordanza mediana ≤ 1,5 pt e
  90° percentile ≤ 3 pt con n ≥ 20; proposta solo se (a) e (b) passano): cambia la
  popolazione di eventi e il testo di apertura della regola lo dichiara. Senza un nuovo
  snapshot lo script continua a stampare «seconda sonda non eseguita» senza numeri.
- **Test di regressione su una risposta grezza reale del 10/10.**
  `audit/test_totals_probe_seconda_analisi.py::test_regressione_risposta_reale_10_10_con_evento_iniziato`
  carica lo snapshot reale `audit/data/totals_probe/2026-10-10_1703/` (risposte grezze
  committate, incluse `soccer_epl.json`) e verifica su Manchester United–Tottenham
  (kickoff 16:30Z, chiamata 17:03:43Z): classificato iniziato, fuori finestra, escluso
  dagli eligible, contato nel referto. I test del file sono 9/9 superati (incluso il
  bordo `commence_time == istante della chiamata`, ora escluso).

### 2.2 Ricalcolo descrittivo dei conteggi PR #59 e #60 senza gli eventi iniziati

Script `audit/totals_probe_senza_avviati.py`, referto completo
`audit/results/totals_probe_senza_avviati.md`. Regola del conteggio (come sopra):
`commence_time` ≤ istante della chiamata → iniziato → escluso dal ricalcolo e contato.
Solo descrittivo: gli esiti dichiarati nelle PR #59 e #60 non cambiano.

Sullo snapshot del 10/10 gli **eventi già iniziati alla chiamata sono 5 su 82** (uno per
lega): Man Utd–Tottenham (−0,0234 gg), Lille–Le Havre (−0,0762 gg), RB Leipzig–Eintracht
Frankfurt (−0,0234 gg), Inter–Parma (−0,0442 gg), Barcelona–Getafe (−0,0213 gg).

Referto `audit/results/totals_probe_senza_avviati.md`, riportato integralmente:

#### 1. Eventi già iniziati alla chiamata

Eventi totali dello snapshot: **82**. Già iniziati (`commence_time` ≤ istante della chiamata): **5**.

| lega | partita | calcio d'inizio (UTC) | giorni mancanti |
|---|---|---|---:|
| Premier League | Manchester United – Tottenham Hotspur | 2026-10-10T16:30:00Z | -0,0234 |
| Ligue 1 | Lille – Le Havre | 2026-10-10T15:14:00Z | -0,0762 |
| Bundesliga | RB Leipzig – Eintracht Frankfurt | 2026-10-10T16:30:00Z | -0,0234 |
| Serie A | Inter Milan – Parma | 2026-10-10T16:00:00Z | -0,0442 |
| La Liga | Barcelona – Getafe | 2026-10-10T16:33:00Z | -0,0213 |

#### 2. PR #59 ricalcolata senza gli eventi iniziati (descrittivo)

Regola D1 invariata: un evento la supera se Pinnacle ha la linea 2,5 OPPURE almeno 3 bookmaker hanno la linea 2,5. Regola D2 invariata per la classificazione delle cause.

| voce | originale (82 eventi) | senza eventi iniziati |
|---|---:|---:|
| eventi | 82 | 77 |
| superano la regola | 56 | 55 |
| non la superano | 26 | 22 |
| copertura della regola | 68,3 % | 71,4 % |

| causa (D2) | originale | senza eventi iniziati |
|---|---:|---:|
| C1 Pinnacle assente | 2 | 2 |
| C2 Pinnacle con linea 1,5 | 1 | 0 |
| C2 Pinnacle con linea 3,5 | 5 | 5 |
| C2 Pinnacle con linea a quarti | 12 | 10 |
| C2 Pinnacle con linea altra mezza | 2 | 1 |
| C2 Pinnacle con linea intera | 4 | 4 |

Soglia dell'85 %: **non raggiunta** in entrambi i conteggi (68,3 % e 71,4 %). L'esito dichiarato nella PR #59 resta «NON superata».

#### 3. PR #60 ricalcolata senza gli eventi iniziati (descrittivo)

Regole P4.1/P4.2 invariate: evento confrontabile se Pinnacle ha una linea ≠ 2,5 e almeno 3 ALTRI bookmaker hanno la 2,5; si confronta P(Over 2,5) delle due griglie (fit generalizzato, differenza assoluta).

| voce | originale | senza eventi iniziati |
|---|---:|---:|
| eventi confrontabili | 42 | 41 |
| mediana di Δ P(Over 2,5) (valore assoluto) | 0,64 pt | 0,54 pt |
| massimo di Δ P(Over 2,5) (valore assoluto) | 4,54 pt | 3,38 pt |

Eventi confrontabili che erano già iniziati (esclusi dal ricalcolo):

| partita | giorni mancanti | Δ P(Over 2,5) (pt) |
|---|---:|---:|
| Manchester United – Tottenham Hotspur | -0,0234 | 4,54 pt |

#### 4. Esiti dichiarati nelle PR #59 e #60 e contaminazione

Gli esiti dichiarati **non cambiano**: qui sotto restano quelli già pubblicati, con accanto se lo snapshot del 10/10 era contaminato.

| esito dichiarato | fonte | snapshot contaminato | ricalcolo senza eventi iniziati |
|---|---|---|---|
| Regola dell'85 %: **NON superata** (56/82 = 68,3 %) | PR #59 §3 | **SÌ** (includeva 5 eventi iniziati) | copertura 71,4 % (55/77): esito invariato |
| 26 eventi non superano la regola, classificati per causa (C1 = 2, C2 varie) | PR #59 §3.1 | **SÌ** | 22 eventi, cause nella tabella §2 |
| 82 eventi, 77 con terna 1X2 Pinnacle, **42 confrontabili** | PR #60 §4.2 | **SÌ** | 41 confrontabili |
| Differenza su P(Over 2,5): mediana 0,64 pt, massimo 4,54 pt | PR #60 §4.2 | **SÌ** | mediana 0,54 pt, massimo 3,38 pt |
| P4.4: **NON utilizzabile** (mediana ≤ 1,5 pt; massimo 4,54 pt > 4 pt) | PR #60 §4.2 | **SÌ** (il massimo era l'evento iniziato Man Utd–Tottenham) | esito invariato: la regola P4.4 resta come dichiarata |
| 77 eventi con linea totals utilizzabile (entro 7 giorni: 53 eventi, 51 utilizzabili) | PR #60 §4.3 | **SÌ** | non ricalcolato: è un conteggio di disponibilità, non dei quattro numeri oggetto di questo punto |

#### 5. Limiti

- Solo descrittivo: nessun esito delle PR #59/#60 è riassegnato e nessuna regola è rivalutata su questo snapshot.
- Lo snapshot resta unico (10/10/2026): i ricalcoli sono sensibilità, non stime di effetto.
- La terna 1X2 usata dalla PR #60 è di 8 ore prima della sonda totals: il disallineamento temporale resta anche senza gli eventi iniziati.
- `commence_time` assente o corrotto non viene classificato come iniziato (come in produzione).

---

## 3. Punto B — i 5 test saltati della suite della PR #61

La suite della PR #61 riportava «1.970 passed, **5 skipped**». I 5 saltati sono i 5 test
della classe `TestGiroCompleto` di `audit/test_replay_topmix_mercato.py`:

| # | test | motivo dello skip (dal `unittest.SkipTest` di `setUpClass`) |
|---|---|---|
| 1 | `test_campione_come_nella_pr49` | cache del frame assente: vedi sotto |
| 2 | `test_devig_di_produzione_identico_alle_colonne_della_pr49` | idem |
| 3 | `test_le_scelte_hanno_esito_e_quota_coerenti` | idem |
| 4 | `test_ogni_riga_ha_un_esito_reale_confrontabile` | idem |
| 5 | `test_parita_con_la_pr49` | idem |

Motivo unico, dal codice: `setUpClass` solleva `SkipTest` se
`audit/output/replay_topmix_mercato_frame.csv` (la cache del frame della PR #49) non
esiste e `REPLAY_MERCATO_FULL ≠ 1`, con il messaggio «cache del frame assente (...): il
giro completo dura ~85 s, si esegue nel check CI Audit oppure con
REPLAY_MERCATO_FULL=1». La cache vive in `audit/output/`, cartella **ignorata da Git**:
in un clone nuovo manca sempre. Nella PR #61 la suite era girata prima del replay, quindi
la cache non c'era e i 5 test sono saltati; nel workflow `Suite completa` gli stessi 5
saltano per lo stesso motivo e il giro completo lo esegue il check `Audit`
(`topmix_audit.yml`) invocando lo script. In questa PR i 5 test sono stati eseguiti con la
cache presente: **5/5 superati** (vedi §5.1).

**Dipendenza dai CSV storici: nessuna.** Nessuno dei 5 legge i 25 CSV di
`audit/data/football_data_storico/`. Il loro input è (i) la cache del frame oppure (ii) i
CSV tracciati `SoccerMath/database/*_2024.csv` e `*_2025.csv` (10 file B365, sempre
completi in un clone: un file tracciato non ammette stati parziali) più il codice di
produzione importato. La condizione «fallire con messaggio esplicito quando la cartella
contiene solo una parte dei 25 file, e saltare solo quando è vuota» non si applica
questi 5 test.

La regola richiesta è implementata dove quei 25 file servono davvero: il nuovo
`audit/test_football_data_storico.py` presidia `audit/data/football_data_storico/` con
esattamente quel comportamento, e entra da solo nella suite (`git ls-files`):

- **cartella senza nessuno dei 25 CSV → skip** con messaggio esplicito (stato attuale);
- **cartella con solo una parte dei 25 → fail** con l'elenco dei mancanti e il messaggio
  «è PARZIALE: presenti N/25 CSV storici. Mancano: ... Completare la cartella con tutti i
  25 file oppure svuotarla» (comportamento verificato su cartella parziale simulata:
  `AssertionError: ... è PARZIALE: presenti 1/25 CSV storici. Mancano: 1718/E0.csv, ...`);
- **25/25 → pass** (e nessun file vuoto).

---

## 4. Punto C — replica del de-vig (punto 1 del prompt della PR #61)

Stato di `audit/data/football_data_storico/`: contiene **solo `README.md`**.
**0 dei 25 CSV attesi sono presenti.** Elenco completo dei mancanti (percorsi relativi
alla cartella; sorgente `mmz4281/<stagione>/<lega>.csv`):

| stagione | directory | CSV attesi | presenti |
|---|---|---|---|
| 2017/18 | `mmz4281/1718/` | `I1.csv`, `E0.csv`, `SP1.csv`, `D1.csv`, `F1.csv` | nessuno |
| 2018/19 | `mmz4281/1819/` | `I1.csv`, `E0.csv`, `SP1.csv`, `D1.csv`, `F1.csv` | nessuno |
| 2019/20 | `mmz4281/1920/` | `I1.csv`, `E0.csv`, `SP1.csv`, `D1.csv`, `F1.csv` | nessuno |
| 2020/21 | `mmz4281/2021/` | `I1.csv`, `E0.csv`, `SP1.csv`, `D1.csv`, `F1.csv` | nessuno |
| 2021/22 | `mmz4281/2122/` | `I1.csv`, `E0.csv`, `SP1.csv`, `D1.csv`, `F1.csv` | nessuno |

Come richiesto: i file mancano e **non produco numeri** — nessuna copertura per
lega/stagione, nessun conteggio di colonne o quote invalide, nessun ΔLogLoss/ΔBrier,
nessun bootstrap, nessuna calibrazione, nessuna sensibilità sulle quote di chiusura. La
regola di decisione del punto 1 resta quella preregistrata nel referto della PR #61,
**senza modificarla**. Non ho scaricato né cercato mirror di `football-data.co.uk` (host
non raggiungibile dal sandbox); la cartella va riempita da Felice con i 25 file originali,
come da `audit/data/football_data_storico/README.md`.

---

## 5. Chiusura — output reali

### 5.1 Suite completa — output reale

Comando equivalente a quello del workflow `Suite completa` (elenco file da `git ls-files`,
97 file `test_*.py` tracciati meno `test_theme_toggle.py`, poi quest'ultimo come script).
Eseguita **in condizioni CI** — cache del frame PR #49 assente da `audit/output/` — per
rendere conto degli skip; il log integrale è in
`audit/results/suite_completa_2026-10-10_filtro.log`:

```text
File pytest: 97
........................................................................ [  4%]
... output truncated ...
.................................................sssss.................. [ 92%]
........................................................................ [ 96%]
........................................................................ [ 99%]
....                                                                     [100%]
=============================== warnings summary ===============================
audit/test_elo_w025_confirmation.py::TestPatchGriglia::test_boot_stats_delta_vs_060_con_griglia_ridotta
  /home/user/SoccerMath2.0/audit/grid_search_ensemble_weight.py:224: RuntimeWarning: invalid value encountered in divide
    rr = np.where(staked > 0, prof / staked, np.nan)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture/warnings.html
============================= slowest 15 durations =============================
46.71s call     SoccerMath/test_apptest_top_mix.py::TestAppTestCalcolaTopMix::test_a_click_top_mix
36.66s setup    audit/test_bookmaker_source_test.py::TestValutazioneCompleta::test_campioni
33.44s setup    audit/test_bookmaker_source_test.py::TestCopertura::test_b365_avg_max_coprono_tutto
11.47s call     audit/test_ng_regression.py::TestNoExtremeNGRegression::test_all_leagues_no_extreme_ng
10.57s call     audit/test_elo_walker_parity.py::TestProvenienzaFixture::test_v3_fixture_rigenerabile_dal_commit_dichiarato
... output truncated ...
3.29s setup    audit/test_elo_walker_parity.py::TestParitaWalker::test_p0_walker_non_tocca_la_cache_globale
1993 passed, 6 skipped, 1 warning, 4773 subtests passed in 302.97s (0:05:02)

--- SoccerMath/test_theme_toggle.py come script ---
2026-10-10 22:15:32.832 WARNING streamlit.runtime.scriptrunner_utils.script_run_context: Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
✅ Run 1 OK - toggle ON (segue tema sistema), nessuna eccezione
✅ Run 2 OK - toggle OFF, CSS light forzato presente (2 blocchi <style>)
✅ Run 3 OK - ritorno a ON, CSS light forzato rimosso, nessuna eccezione
✅ Run 4 OK - rerun generico senza crash

🎉 TUTTI I TEST PASSATI: nessun crash in nessuno stato del toggle.

Suite completa exit=0; test_theme_toggle exit=0
```

Esito: **1.993 passed, 6 skipped, 4.773 subtests passed, 1 warning**; exit 0;
`test_theme_toggle.py` exit 0. I 6 skip (elenco completo dai messaggi, §5.1.1):

| # | test | motivo |
|---|---|---|
| 1 | `audit/test_football_data_storico.py::test_25_csv_o_cartella_vuota_mai_stato_parziale` | nessuno dei 25 CSV storici: skip come da regola (punto C) |
| 2-6 | `audit/test_replay_topmix_mercato.py::TestGiroCompleto::` (5 test, vedi §3) | cache del frame assente (condizioni CI) |

#### 5.1.1 Giro completo rieseguito con la cache

Gli stessi 5 test della PR #61, con la cache ripristinata (come nel check `Audit`):

```text
audit/test_replay_topmix_mercato.py::TestGiroCompleto::test_campione_come_nella_pr49 PASSED
audit/test_replay_topmix_mercato.py::TestGiroCompleto::test_devig_di_produzione_identico_alle_colonne_della_pr49 PASSED
audit/test_replay_topmix_mercato.py::TestGiroCompleto::test_le_scelte_hanno_esito_e_quota_coerenti PASSED
audit/test_replay_topmix_mercato.py::TestGiroCompleto::test_ogni_riga_ha_un_esito_reale_confrontabile PASSED
audit/test_replay_topmix_mercato.py::TestGiroCompleto::test_parita_con_la_pr49 PASSED

============================== 5 passed in 2.75s ===============================
```

### 5.2 CI GitHub — esiti reali per workflow (step eseguiti e saltati)

_In aggiornamento dopo l'apertura della PR: questa sezione viene riempita con gli esiti
reali dei check GitHub Actions senza toccare le regole preregistrate._

### 5.3 Replay `topmix_mercato_v3` — output reale

Comando (senza `--write`, senza rete, output verso `/tmp` per non toccare i referti
committati): `.venv/bin/python audit/replay_topmix_mercato.py --report /tmp/... --json
/tmp/... --righe /tmp/...`. Log integrale in
`audit/results/replay_topmix_mercato_filtro.log`:

```text
costruzione del frame (Poisson di produzione + Elo walker + quote)...
frame costruito in 114 s (7354 righe)
...
## 1. Confronto con la PR #49

| Voce | Fonte PR #49 | n PR #49 | n replay | Δn | hit PR #49 | hit replay | Δhit | coincide |
|---|---|---|---|---|---|---|---|---|
| scelte_mercato | §4, pooled OOS, mercato B365 pre (prop.) | 1302 | 1302 | +0 | 0.6751 | 0.6751 | +0.0000 | SÌ |
| accordo | §4d tabella B, scelte del modello CON consenso | 1144 | 1144 | +0 | 0.6818 | 0.6818 | +0.0000 | SÌ |
| senza_accordo | §4d tabella B, scelte del modello SENZA consenso | 335 | 335 | +0 | 0.4358 | 0.4358 | +0.0000 | SÌ |

**Esito del confronto: PARITÀ** (tolleranze dichiarate: Δn ≤ 0, |Δhit| ≤ 0.0005).
...
[esito] parita' con la PR #49: SÌ
```

**Parità verificata: 1.302 / 1.144 / 335, Δn = +0** su tutte e tre le righe; exit 0.
Nota di trasparenza: il frame costruito qui ha 7.354 righe contro le 7.347 del log della
PR #61; la differenza di 7 righe sta nelle sole righe 2026/27 (272, dai `_Live.csv`), che
non entrano nel campione (2024/25 + 2025/26 con modello e terna B365 pre): campione 3.504
e parità 1302/1144/335 invariate. Non ho identificato il commit responsabile della
differenza di quelle 7 righe.

### 5.4 Ciò che non è stato verificato

- **Punto C (de-vig OOS 2017/18–2021/22):** nessun numero — 0/25 CSV presenti (§4). La
  regola del punto 1 non è stata applicata ad alcun dato.
- **Seconda sonda totals:** non lanciata (vincolo). Il comportamento su uno snapshot nuovo
  è coperto solo da test offline; la regola (a)(b)(c) non è applicata a nessuno snapshot
  reale nuovo (il baseline 10/10 resta escluso per design).
- **Filtro di concordanza fuori campione:** l'ipotesi è valutata solo su 2024/25 + 2025/26,
  stagioni già usate dal progetto (limite dichiarato: i dati non sono vergini). Nessuna
  verifica su 2026/27 o su scelte future; nessuna verifica con quote live di produzione
  (il replay usa B365 pre dai CSV).
- **Nessuna ricerca di soglie alternative** al filtro (vietata dalla regola): non esistono
  esiti per soglie diverse da 0,75 / 0,05.
- **Regressione logistica:** solo specificazione lineare in logit(p_m) e scarto (e parti
  ±); non verificata la robustezza a specificazioni alternative, né un effetto causale.
- **Nessuna chiamata a The Odds API**, nessuna chiave usata o stampata, nessuna scrittura
  nel Registro, nessun `--write`, nessuna modifica a `SoccerMath/` o `app.py`.
- **CI:** esiti dei workflow raccolti dopo l'apertura della PR (§5.2); eventi schedulati o
  workflow manuali (`totals_probe`) non eseguiti per vincolo.
- La PR non viene fusa (richiesto).
