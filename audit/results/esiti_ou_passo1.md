# Passo 1 di 3 — gli esiti dei pronostici O/U

- **Pull request:** https://github.com/iFelice/SoccerMath2.0/pull/78
- **Branch:** `arena/76d5a34e-soccermath2-0`
- **Commit:** `594e36cfbe9f9a75b279cbec4c088db0b86d1f41` — «Esiti dei pronostici O/U: il grading cerca la partita per (lega, giorno)»
- Data del referto: 2026-10-18 (ora del sandbox: 21:30 UTC). Passo 1 di 3: in questo passo c'e' solo il grading degli esiti O/U; gli altri due arrivano sullo stesso branch dopo la verifica.

## 0. Il problema e la regola

Nessuna voce O/U del registro riceveva mai un esito. `entry_registro_totals` salva `giornata=None` e, come `match_id`, l'id dell'evento The Odds API (stringa esadecimale, es. `7d3160040958fe21778fd5ee485666c3`); `_applica_esiti` considerava solo le righe **con** giornata e cercava il risultato col `match_id` di football-data. Nel registro di produzione dieci voci O/U del 16–18/10 erano bloccate su ⏳ (es. Frosinone–Sassuolo, finita 4-2).

Regola del ramo nuovo (`_esiti_senza_giornata`, dentro `_applica_esiti`):

| situazione della riga in attesa | cosa fa il grading |
|---|---|
| `giornata` valorizzata **e** `match_id` numerico (id football-data) | percorso per giornata di sempre (**invariato**: 1X2 visibili e registro ombra) |
| `giornata` assente **oppure** `match_id` non numerico | GET `/v4/competitions/{codice}/matches?dateFrom=…&dateTo=…&status=FINISHED`, finestra [giorno del kickoff, giorno dopo] |
| 1 partita corrispondente (nomi canonici `resolve_team_name` con `mapped=True` su entrambi + stessa data) | `risultato_reale` «gh-ga», esito da `esito_mercato`, id football-data in `fd_match_id` (campo NUOVO) |
| 0 partite o più di 1 | la riga resta ⏳ e il **motivo** va nel log |

`match_id` **non** cambia mai: e' la chiave anti-doppioni della riga. Una sola chiamata per `(lega, giorno)`, in cache nello stesso giro (vale anche per il registro ombra, che condivide la cache). Le voci gia' presenti si sistemano al primo «Controlla i risultati»: nessuna migrazione a parte.

## 1. Impronte del selettore (Python 3.11)

Calcolate con `SoccerMath/test_versione_selettore.py` (`impronta_attuale()` e `impronta_ou_attuale()`), Python 3.11.2.

| impronta | PRIMA (HEAD `8a83d53`) | DOPO (commit `594e36c`) |
|---|---|---|
| `impronta_attuale` (1X2, `topmix_mercato_v3`) | `1d2787b0f45b0f91a6ba651809b6e9ecdb2ba7dec35972dafdb40814186a4bb5` | `1d2787b0f45b0f91a6ba651809b6e9ecdb2ba7dec35972dafdb40814186a4bb5` |
| `impronta_ou_attuale` (`totals_mercato_v1`) | `fbb0cb99c42e589c3296a8bc4185c7f5b284bc3d1a67b7e621dabc7517431d8c` | `fbb0cb99c42e589c3296a8bc4185c7f5b284bc3d1a67b7e621dabc7517431d8c` |

**Identiche.** `entry_registro_totals` e `righe_pronostici_dalle_quote` (dentro l'impronta O/U) non sono stati toccati: il campo `fd_match_id` nasce nel grading, non nella costruzione della riga.

```
$ .venv/bin/python -m pytest -q -rfE --tb=short -p no:cacheprovider SoccerMath/test_versione_selettore.py
.........                                                                [100%]
9 passed in 1.45s
```

## 2. diff stat

```
$ git diff --stat 8a83d539682deb45c94876b6483524ac73ec70ae 594e36cfbe9f9a75b279cbec4c088db0b86d1f41
 SoccerMath/app.py                    | 175 ++++++++++++-
 SoccerMath/prediction_registry.py    |   7 +
 SoccerMath/test_esiti_ou_registro.py | 465 +++++++++++++++++++++++++++++++++++
 3 files changed, 642 insertions(+), 5 deletions(-)
```

- `SoccerMath/app.py`: i cinque helper (`_match_id_numerico`, `_giorno_kickoff_riga`, `_coppia_canonica`, `_coppia_canonica_partita`, `_partite_finite`), `_esiti_senza_giornata` e la biforcazione dentro `_applica_esiti` (il ramo per giornata e il ramo giornata-0 restano identici).
- `SoccerMath/prediction_registry.py`: `FD_MATCH_ID_FIELD = "fd_match_id"`.
- `SoccerMath/test_esiti_ou_registro.py`: nuovo file di test (entra da solo nella suite: `git ls-files` lo vede).

## 3. Test (a)–(d) — `SoccerMath/test_esiti_ou_registro.py`

Nessuna rete: football-data e' simulato da un oggetto che risponde alle GET di `app.requests` (`Rete`, contatore delle chiamate incluso). Nessuna chiave, nessuna attesa, nessun replay, nessuna scrittura nel registro di produzione.

Fixture: le righe vengono dallo **snapshot del 16/10** (`audit/totals_snapshot_fixture.payload_snapshot()`, `generato_il 2026-10-16T13:17:55Z`, 97 eventi) tramite il codice vero `app.righe_pronostici_dalle_quote`, e le voci da `app.entry_registro_totals`. La soglia di ammissione O/U della *fixture* e' 0,60 invece di 0,67 (knob di costruzione: il modulo non si tocca, `SOGLIA_OU` resta 0,67 in `totals_mercato.py`): serve a far nascere dagli eventi reali dello snapshot le tre voci del test (a), Frosinone–Sassuolo compreso (Over a 0,6688, un soffio sotto 0,67). Quote, fit, probabilita', nomi e kickoff sono quelli dello snapshot.

```
$ .venv/bin/python -m pytest -q -s -p no:cacheprovider SoccerMath/test_esiti_ou_registro.py -v
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.1.1, pluggy-1.7.0
rootdir: /home/user/SoccerMath2.0
plugins: anyio-4.15.1
collected 6 items

SoccerMath/test_esiti_ou_registro.py
(a) voci O/U dallo snapshot del 16/10
partita                           esito prima   esito dopo  risultato  fd_match_id
Frosinone-Sassuolo                          ⏳            ✅        4-2          401
Bayern Munich-RB Leipzig                    ⏳            ❌        0-0          402
Getafe-Rayo Vallecano                       ⏳            ✅        1-1          403
match_id invariati: True
.
(b) voce in stile PR #76 (origin top_mix, giornata None)
partita                           esito prima   esito dopo  risultato  fd_match_id
Frosinone-Sassuolo                          ⏳            ✅        4-2          401
match_id invariati: True
..
(c) partita doppia e partita non trovata
partita                           esito prima   esito dopo  risultato  fd_match_id
Frosinone-Sassuolo                          ⏳            ⏳       None         None
Parma-Torino                                ⏳            ⏳       None         None
match_id invariati: True
warning: root:Grading O/U Frosinone-Sassuolo del 2026-10-16 (OVER_2.5): 2 partite corrispondenti, resta ⏳ | root:Grading O/U Parma-Torino del 2026-10-19 (UNDER_2.5): nessuna partita finita, resta ⏳
.
(d) stesso giro: 1X2 per giornata + O/U per data
partita                           esito prima   esito dopo  risultato  fd_match_id
Frosinone-Sassuolo                          ⏳            ✅        2-0         None
Frosinone-Sassuolo                          ⏳            ❌        2-0          501
match_id invariati: True
.
(d) registro misto: 1X2 e ombra
partita                           esito prima   esito dopo  risultato  fd_match_id
Frosinone-Sassuolo                          ⏳            ✅        2-0         None
Bologna-Inter Milan                         ⏳            ✅        1-1         None
Juventus-Lazio                              ⏳            ⏳       None         None
Frosinone-Sassuolo                          ⏳            ✅        4-2         None
Bologna-Inter Milan                         ⏳            ❌        2-0         None
match_id invariati: True
.

============================== 6 passed in 29.91s ==============================
```

### (a) `test_a_voci_ou_dallo_snapshot_del_16_10`

Tre voci create da `entry_registro_totals` su righe dello snapshot del 16/10; football-data simulato una chiamata per `(lega, giorno)`.

| partita (lega, kickoff) | mercato | esito prima | esito dopo | risultato_reale | `fd_match_id` | `match_id` (invariato) |
|---|---|---|---|---|---|---|
| Frosinone–Sassuolo (Serie A, 16/10 18:45Z) | `OVER_2.5` | ⏳ | **✅** (4-2, 6 gol) | `4-2` | `401` | `7d3160040958fe21778fd5ee485666c3` |
| Bayern Munich–RB Leipzig (Bundesliga, 17/10 16:30Z) | `OVER_2.5` | ⏳ | **❌** (0-0) | `0-0` | `402` | `9a64448205fdc4b95f45641bb946706c` |
| Getafe–Rayo Vallecano (La Liga, 19/10 19:00Z) | `UNDER_2.5` | ⏳ | **✅** (1-1, 2 gol) | `1-1` | `403` | `4a88bc4de574d43ef34677fd8d78722f` |

Il test asserisce anche: `giornata=None` sulle tre voci, `origin="mercato_ou"`, `(aggiornate, pending) = (3, 3)`, **3 GET in totale** (una per `(lega, giorno)`) e **0 GET in più** al secondo giro con la stessa cache.

### (b) `test_b_voce_in_stile_pr76_senza_giornata`

Voce costruita con `app.argomenti_registro_top_mix_mercato` + `app.build_prediction_entry` (stesso percorso di PR #76): `origin=top_mix`, `selector_version=topmix_mercato_v3`, `giornata=None`, `match_id` = id The Odds API, `mercato_standard=OVER_2.5`. Risultato simulato Frosinone–Sassuolo 4-2.

| campo | prima | dopo |
|---|---|---|
| `esito` | ⏳ | **✅** |
| `risultato_reale` | `None` | `4-2` |
| `fd_match_id` | assente | `401` |
| `match_id` | `7d3160040958fe21778fd5ee485666c3` | `7d3160040958fe21778fd5ee485666c3` (invariato) |
| `giornata` | `None` | `None` (invariata) |

### (c) `test_c_partita_non_trovata_e_partita_doppia` e `test_c2_riga_senza_kickoff_resta_in_attesa_con_un_motivo`

| caso | partita | partite nella finestra | esito dopo | `risultato_reale` | `fd_match_id` | warning |
|---|---|---|---|---|---|---|
| doppia | Frosinone–Sassuolo (16/10) | 2 con gli stessi nomi e la stessa data | ⏳ | `None` | assente | «Grading O/U Frosinone-Sassuolo del 2026-10-16 (OVER_2.5): 2 partite corrispondenti, resta ⏳» |
| non trovata | Parma–Torino (19/10) | 1, ma Monza–Cagliari | ⏳ | `None` | assente | «Grading O/U Parma-Torino del 2026-10-19 (UNDER_2.5): nessuna partita finita, resta ⏳» |
| senza kickoff | Frosinone–Sassuolo, `kickoff_utc=""` | (nessuna GET: senza finestra non si chiama football-data) | ⏳ | `None` | assente | «Grading O/U senza estremi: … resta ⏳» |

`(aggiornate, pending) = (0, 2)` / `(0, 1)`: nessun esito inventato.

### (d) `TestInvarianti1X2eOmbra` — registro di prova misto

Due prove. La prima (`test_d_1x2_e_ombra_come_prima`) prende 3 righe 1X2 visibili + 2 righe ombra (tutte con `giornata=7` e `match_id` numerico), ne fa due copie identiche e le gradua: una con `_applica_esiti` di oggi, una con il **ramo per giornata com'era prima** (`_applica_esiti_prima`, copia di HEAD) incorporato nel test come riferimento.

| riga | mercato | risultato simulato | esito oggi | esito riferimento (prima) | `fd_match_id` |
|---|---|---|---|---|---|
| 1X2 `501` Frosinone–Sassuolo | `1` | 2-0 | ✅ | ✅ (uguale) | assente |
| 1X2 `502` Bologna–Inter Milan | `X` | 1-1 | ✅ | ✅ (uguale) | assente |
| 1X2 `599` Juventus–Lazio | `1` | partita assente | ⏳ | ⏳ (uguale) | assente |
| ombra `503` Frosinone–Sassuolo | `OVER_2.5` | 4-2 | ✅ | ✅ (uguale) | assente |
| ombra `504` Bologna–Inter Milan | `GG` | 2-0 | ❌ | ❌ (uguale) | assente |

Asserzioni: `(aggiornate, pending)` identici `(4, 5)`; `esito` e `risultato_reale` identici riga per riga; **le stesse GET nello stesso ordine** (1 chiamata, con `matchday`, **nessun `dateFrom`**) e quindi nessuna chiamata per data per le righe 1X2/ombra; il campo `fd_match_id` **non** compare su nessuna riga graduata per giornata.

La seconda (`test_d2_le_ou_non_cambiano_il_grading_per_giornata`) mette nello stesso giro una riga 1X2 e una O/U sulla stessa partita (2-0): la 1X2 passa dal ramo per giornata (`✅`, nessun `fd_match_id`), l'O/U dal ramo per data (`❌`, `risultato_reale="2-0"`, `fd_match_id=501`); 2 GET in totale, una per ramo.

## 4. Suite completa a lotti

Elenco dei file: `git ls-files | grep -E '(^|/)test_[^/]*\.py$' | grep -vx 'SoccerMath/test_theme_toggle.py'` → **116 file** (115 tracciati + il nuovo test). Divisi in 8 lotti (i file AppTest, i più lenti, al massimo due o tre per lotto). Un'invocazione per lotto, `timeout 900`:

```
mapfile -t F < /tmp/batch/lottoNN.txt
timeout 900 .venv/bin/python -m pytest -q -rfE -rs --tb=line -p no:cacheprovider "${F[@]}"
```

| lotto | file | esito |
|---|---|---|
| 01 | 16 | **362 passed, 31 skipped, 993 subtests passed** in 279.83s (0:04:39) |
| 02 | 15 | **205 passed, 18 skipped, 16 subtests passed** in 88.97s (0:01:28) |
| 03 | 14 | 1 failed, **289 passed**, 8 skipped, 8 subtests passed in 140.21s (0:02:20) |
| 04 | 15 | 7 failed, **429 passed**, 2 skipped, 23 subtests passed in 141.02s (0:02:21) |
| 05 | 14 | **195 passed, 13 skipped** in 46.25s |
| 06 | 14 | 2 failed, **228 passed**, 4 skipped, 3717 subtests passed in 130.50s (0:02:10) |
| 07 | 14 | **214 passed, 7 skipped, 40 subtests passed** in 33.90s |
| 08 | 14 | 1 failed, **341 passed**, 2 skipped, 1175 subtests passed in 112.41s (0:01:52) |
| **totale** | **116** | **2263 passed, 11 failed, 85 skipped, 5972 subtests passed** |

### 4b. Gli 11 falliti sono preesistenti (verificati su HEAD)

Nessuno riguarda questo lavoro. Il clone del sandbox e' **shallow** (`git rev-list --count HEAD` = 1): 10 test cercano commit/blob storici che qui non esistono. L'undicesimo e' un fuso orario. Tutti e 11 sono stati rieseguiti su HEAD (`8a83d53`) in un worktree pulito (`git worktree add /tmp/base8a83d HEAD`), con lo **stesso** esito:

| test | motivo (dall'output reale) |
|---|---|
| `audit/test_elo_probs_equivalence.py::TestEquivalenzaBitExact::test_commit_dichiarato_esiste_nel_clone` | `fatal: git cat-file: could not get object info` |
| `audit/test_elo_s3_parity.py` (4 test di provenienza) | `commit=9957f417… non presente nel clone` |
| `audit/test_reconstruct_topmix_match.py` (3 test) | `ref git non risolto: 0695e9e6…` / `nessun commit su origin/main prima di …` |
| `audit/test_elo_walker_parity.py` (2 test) | `git worktree non disponibile o commit non estraibile: fatal: invalid reference: 6f9505b9…` |
| `SoccerMath/test_apptest_scheda_pronostici.py::TestSchedaPronostici::test_08_il_periodo_e_un_calcolo_nuovo_non_una_tabella_mista` | `AssertionError: 'sab 31/10, 00:59 ⏳' != 'ven 30/10, 23:59 ⏳'` (un'ora: conversione UTC→Europa/Roma attorno al cambio d'orario, indipendente dal grading) |

```
$ cd /tmp/base8a83d && pytest -q -rfE --tb=line -p no:cacheprovider \
    audit/test_elo_probs_equivalence.py audit/test_elo_s3_parity.py \
    audit/test_reconstruct_topmix_match.py audit/test_elo_walker_parity.py
10 failed, 35 passed, 1 skipped in 40.74s
$ cd /tmp/base8a83d && pytest -q -rfE --tb=line -p no:cacheprovider SoccerMath/test_apptest_scheda_pronostici.py
1 failed, 13 passed, 1 skipped, 117 subtests passed in 104.98s
```

Gli **85 skip** hanno la stessa origine (clone shallow e dati opzionali assenti nel sandbox). `-rs` li dichiara uno per uno, e il motivo e' scritto nei test:

| motivo riportato da `-rs` | lotti | conteggi dichiarati |
|---|---|---|
| «Snapshot pinnato non raggiungibile (clone shallow?)» | 01, 02, 05, 07 | 12 + 15 (lotto 01), 17 (lotto 02), 8 (lotto 05), 7 (lotto 07) |
| «CSV dello snapshot fissato non raggiungibile (clone shallow?)» | 01 | 4 |
| «cache del frame assente (`audit/output/replay_topmix_mercato_frame.csv`)» | 05 | 5 |
| «commit/blob non raggiungibile (clone shallow)» | 02, 04, 08 | 1 (blob `16d4e73`), 2 (commit `b837823`), 1 (commit base `27e482e`) |
| «Impossibile leggere snapshot da git» / «git worktree non disponibile» | 06 | 3 + 1 |
| `audit/data/football_data_storico/` senza i 25 CSV storici | 08 | 1 |

Nessuno skip e' riconducibile a questo commit: nessuno dei tre file toccati (`app.py`, `prediction_registry.py`, `test_esiti_ou_registro.py`) dichiara skip, e i sei test nuovi passano tutti (§3).

## 5. `test_theme_toggle.py` come script

Non e' un test pytest (asserzioni a livello di modulo e `sys.exit(0)`), si esegue come script, come fa `test_suite.yml`:

```
$ .venv/bin/python SoccerMath/test_theme_toggle.py
✅ Run 1 OK - toggle ON (segue tema sistema), nessuna eccezione
✅ Run 2 OK - toggle OFF, CSS light forzato presente (2 blocchi <style>)
✅ Run 3 OK - ritorno a ON, CSS forzato rimosso, nessuna eccezione
✅ Run 4 OK - rerun generico senza crash

🎉 TUTTI I TEST PASSATI: nessun crash in nessuno stato del toggle.
EXIT=0
```

## 6. Vincoli rispettati

| vincolo | stato |
|---|---|
| impronte `impronta_attuale` / `impronta_ou_attuale` (Python 3.11) identiche prima e dopo | ✅ §1 |
| nessuna attesa (sleep, wait, polling): CI osservata **una sola volta**, senza attese | ✅ §7 |
| suite con `timeout 900` per invocazione (8 invocazioni) | ✅ §4 |
| nessun replay `--write` | ✅ nessun replay eseguito |
| nessuna chiave, nessuna rete nei test (football-data simulato) | ✅ §3 |
| nessun merge | ✅ PR aperta, non mergiata |
| `git status --porcelain` vuoto | ✅ §7 |

## 7. Stato del repository e CI

```
$ git status --porcelain
(vuoto)
```

CI osservata una sola volta, subito dopo l'apertura della PR, senza nessuna attesa o riesecuzione:

```
$ gh run list --branch arena/76d5a34e-soccermath2-0 --limit 20
in_progress		Esiti dei pronostici O/U: il grading cerca la partita per (lega, giorno)	Replay Top Mix legacy (walk-forward, no-leakage)	arena/76d5a34e-soccermath2-0	pull_request	39168054414	7s	0m
in_progress		Esiti dei pronostici O/U: il grading cerca la partita per (lega, giorno)	Audit Top Mix (sola lettura)	arena/76d5a34e-soccermath2-0	pull_request	39168054343	7s	0m
in_progress		Esiti dei pronostici O/U: il grading cerca la partita per (lega, giorno)	Suite test completa	arena/76d5a34e-soccermath2-0	pull_request	39168054538	7s	0m
```

I tre workflow della PR erano `in_progress` al momento dell'osservazione (7 s dall'avvio). L'esito della CI non e' stato atteso: la verifica di questo passo e' la suite eseguita in locale, riportata per intero al §4.
