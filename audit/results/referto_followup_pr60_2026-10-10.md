# Referto di audit follow-up PR #60 — 2026-10-10

Branch `arena/3cf76880-soccermath2-0`, base `cf7346e084573a6498e606d0847fa2c605e9b9ff` (PR #60 già mergiata).

Vincoli: audit di sola lettura; nessuna modifica a `SoccerMath/` né a `SoccerMath/app.py`; nessun replay con `--write`; nessuna chiamata a The Odds API; la chiave di The Odds API non deve comparire in alcun output, log o file. La sonda totals non verrà lanciata. Nessuna scrittura nel Registro.

## Regole preregistrate — punti 1 e 4

Le regole seguenti sono fissate in questa sezione prima dei risultati del presente referto. La sezione non verrà modificata dopo l'aggiunta dei risultati.

### Punto 1 — replica del test di de-vig su stagioni mai usate

- **Dati e campione:** CSV football-data per le stagioni 2017/18, 2018/19, 2019/20, 2020/21 e 2021/22, per I1, E0, SP1, D1 e F1; percorso sorgente `mmz4281/<stagione>/<lega>.csv`; archivio locale `audit/data/football_data_storico/`. Pinnacle pre-chiusura (`PSH/PSD/PSA`) è il campione principale; Pinnacle di chiusura (`PSCH/PSCD/PSCA`) è la sensibilità.
- **Copertura e quote non valide:** prima dei risultati si riporta, per lega × stagione, presenza delle colonne, righe con terna completa e quote non valide. Quote nulle/non numeriche o ≤ 1 sono escluse e contate; i campioni di scoring sono appaiati e richiedono terna 1X2 valida e risultato noto.
- **Metodi e metriche:** proporzionale, potenza e Shin. Si riportano ΔLogLoss e ΔBrier appaiati (metodo − proporzionale); negativo significa meglio. Bootstrap a blocchi lega × stagione × data, 2000 repliche. La metrica primaria è LogLoss; Brier è secondaria. Le quote di chiusura sono solo sensibilità.
- **Regola di decisione, solo sulle quote pre-chiusura:** un metodo M (potenza o Shin) passa se l'IC al 97,5% di ΔLogLoss (M − proporzionale) è interamente sotto zero (97,5% perché i confronti sono due). Se passano entrambi, si propone quello con LogLoss più bassa; se l'IC 95% della loro differenza appaiata contiene lo zero, si propone la potenza. Se non passa nessuno, resta il proporzionale e la questione de-vig è chiusa: nessun altro test.
- **Descrittivo:** per l'esito più probabile (argmax), per ciascuno dei tre metodi e nelle fasce [0,55-0,65), [0,65-0,75), ≥0,75, si riporta n, p media, frequenza osservata, f − p con segno e IC 95% a blocchi.

### Punto 4 — preparazione della seconda sonda totals (senza lanciarla)

Per gli eventi con calcio d'inizio da 0 a 7 giorni dopo la chiamata:

- **(a) Copertura:** passa se almeno l'85% degli eventi ha una linea totals utilizzabile: Pinnacle con qualunque linea oppure almeno 3 bookmaker con la linea 2,5.
- **(b) Concordanza:** sugli eventi con Pinnacle su una linea diversa da 2,5 e almeno 3 *altri* bookmaker con la 2,5, si confronta P(Over 2,5) delle due griglie. Passa se mediana ≤1,5 punti percentuali e 90° percentile ≤3 punti percentuali, con almeno 20 eventi confrontabili; con meno di 20 l'esito è «non decidibile».
- **(c) Proposta:** totals con fit generalizzato è proponibile per la produzione solo se (a) e (b) passano entrambe.

L'analisi non si applica allo snapshot del 10/10. Senza un nuovo snapshot lo script deve stampare «seconda sonda non eseguita» e uscire senza risultati numerici.

---

## 1. Punto 1 — disponibilità dei CSV storici

### Esito del punto 1

**Non eseguito per indisponibilità della fonte.** L'host `football-data.co.uk` non è raggiungibile dal sandbox, la cui uscita di rete è limitata agli host autorizzati. Non ho tentato di scaricare i CSV né usato mirror o dati sostitutivi. Come richiesto, mi fermo qui sul punto 1: Felice fornirà i 25 file originali nei percorsi elencati in `audit/data/football_data_storico/README.md`. Di conseguenza non esistono copertura per lega/stagione, conteggi di quote invalide né metriche OOS; non riporto numeri stimati o presunti.

## 2. Chiarimento dei conteggi PR #60 — campione di 3.504 partite

Ricalcolo offline sul medesimo campione B365 2024/25 + 2025/26 (3.504 righe con quote B365 1X2 e O/U 2,5 valide), usando le tre terne de-vig e la soglia di selezione `p ≥ 0,55`. «Centri» = esiti reali corretti fra le scelte.

### Insieme completo di scelte sopra soglia

| metodo | scelte sopra soglia | centri | hit rate |
|---|---:|---:|---:|
| proporzionale | 1.302 | 879 | 67,51% |
| potenza | 1.465 | 971 | 66,28% |
| Shin | 1.407 | 935 | 66,45% |

### Solo scelte aggiunte rispetto al proporzionale

| metodo | n aggiunte | centri | hit rate | p media del metodo | p media proporzionale sulle stesse partite |
|---|---:|---:|---:|---:|---:|
| potenza | 163 | 92 | 56,44% | 55,6234% | 54,3815% |
| Shin | 105 | 56 | 53,33% | 55,4927% | 54,6280% |
| proporzionale (riferimento) | — | — | — | — | — |

Quindi **56,4% e 53,3% si riferivano esclusivamente alle scelte aggiunte**, non all'insieme completo selezionato da potenza o Shin. Sul set completo i rispettivi hit rate sono 66,28% e 66,45%, contro 67,51% del proporzionale. Il campione e le scelte sono appaiati; l'esito argmax non cambia, cambiano le sole ammissioni alla soglia.

## 3. Diagnosi dell'evento fuori soglia — Manchester United–Tottenham

Dati letti solo dai file locali dello snapshot totals del 10/10 (ora spostato in `audit/data/totals_probe/2026-10-10_1703/`) e dal locale `SoccerMath/database/live_odds.json`; nessuna nuova chiamata. La chiamata totals è delle **17:03:43Z**; il kickoff registrato è **16:30:00Z**, quindi lo snapshot totals è arrivato 33m43s dopo il kickoff.

### Quote totals grezze e aggiornamento del bookmaker

| bookmaker | linea | Over | Under | `last_update` (UTC) |
|---|---:|---:|---:|---|
| MyBookie.ag | 2,5 | 2,10 | 1,70 | 2026-10-10 17:01:56 |
| Tipico | 2,5 | 2,30 | 1,55 | 2026-10-10 17:03:21 |
| Pinnacle | 2,25 | 1,91 | 1,97 | 2026-10-10 17:03:37 |
| PMU (FR) | 1,5 | 1,34 | 2,48 | 2026-10-10 17:03:37 |
| LeoVegas (SE) | 2,5 | 2,33 | 1,47 | 2026-10-10 17:03:22 |
| Unibet (SE) | 2,5 | 2,33 | 1,55 | 2026-10-10 17:03:04 |
| Unibet (NL) | 1,5 | 1,43 | 2,63 | 2026-10-10 17:03:38 |
| Nordic Bet | 2,0 | 1,72 | 1,95 | 2026-10-10 17:03:04 |
| Coolbet | 2,0 | 1,73 | 2,12 | 2026-10-10 17:02:51 |
| Matchbook | 2,5 | 2,54 | 1,63 | 2026-10-10 17:03:37 |

### Quote 1X2 e griglie

Le quote 1X2 Pinnacle usate sono casa **1,75**, pareggio **4,21**, trasferta **4,45**, dallo snapshot `live_odds.json` delle **09:08:52Z**. La loro terna de-vig proporzionale è **55,2811% / 22,9791% / 21,7398%**.

| griglia | vincolo totals usato | λ casa | μ trasferta | ρ | P(Over 2,5) della griglia |
|---|---|---:|---:|---:|---:|
| A — linea Pinnacle 2,25 | Pinnacle Over/Under 2,25 = 1,91 / 1,97; probabilità equa Over 2,25 = 50,7732% | 1,585089 | 0,870955 | 0,093344 | 44,4863% |
| B — consenso degli altri libri a 2,5 | mediana di 5 probabilità Over 2,5 de-vigate: 39,9485% | 1,487466 | 0,795671 | 0,139284 | 39,9485% |

La differenza A − B è **+4,5378 punti percentuali** (44,4863% − 39,9485%). I cinque libri non-Pinnacle con linea 2,5 sono MyBookie, Tipico, LeoVegas (SE), Unibet (SE) e Matchbook.

**Diagnosi temporale:** non emerge un `last_update` distante dagli altri tale da spiegare lo scarto come quota evidentemente non aggiornata. L'aggiornamento più vecchio è MyBookie alle 17:01:56Z, 1m47s prima della chiamata; il più recente è Unibet (NL) alle 17:03:38Z, 5s prima. Il divario fra questi due aggiornamenti è **1m42s**; Pinnacle è aggiornato 6s prima della chiamata. La differenza è quindi più compatibile con un disaccordo effettivo di prezzi/linee fra i bookmaker che con un singolo aggiornamento molto arretrato. Caveat importante: l'evento era già iniziato e la terna 1X2 impiegata era quasi otto ore più vecchia della sonda totals; il fit accoppia dunque fonti non contemporanee e non consente una conclusione causale più forte.

**La conclusione sulla regola della PR #60 non cambia: «non utilizzabile su quello snapshot».** Questa diagnosi non applica né rivaluta la regola della PR #60.

## 4. Preparazione della seconda sonda totals — non lanciata

- Le cinque risposte grezze e `_summary.json` del 10/10 sono state spostate, senza modificarne il contenuto, in `audit/data/totals_probe/2026-10-10_1703/`.
- `audit/totals_probe.py` riserva una nuova directory UTC per ogni run. Il nome ordinario è `AAAA-MM-GG_HHMM`; se due esecuzioni cadono nello stesso minuto, un suffisso numerico distingue le directory senza sovrascrivere la prima.
- `.github/workflows/totals_probe.yml` passa esplicitamente alle analisi offline la directory creata in quel run. Non ho avviato il workflow né lo script di acquisizione.
- `audit/totals_probe_seconda_analisi.py` contiene e stampa in testa la regola preregistrata sopra, seleziona un solo snapshot successivo al baseline e rifiuta quello del 10/10. Senza un run nuovo stampa **«seconda sonda non eseguita»**, esce senza numeri di risultato e non crea il referto.
- Test di regressione con `get_json` simulato: due run consecutivi nello stesso minuto creano `2026-10-10_1703/` e `2026-10-10_1703_02/`; il file grezzo del primo run resta identico dopo il secondo. Nessuna richiesta HTTP è stata eseguita dal test.

## 5. Chiusura — output reali locali

La prima esecuzione locale della suite è stata avviata sul clone shallow: 10 test che consultano commit storici sono falliti perché quegli oggetti Git non erano nel clone. Ho poi eseguito `git fetch --unshallow origin` (senza cambiare branch o worktree) e ripetuto la suite. L'output completo della prima esecuzione è conservato in `audit/results/suite_completa_2026-10-10_followup_shallow.log`; qui sotto è incollata la seconda esecuzione, equivalente al comando del workflow con storia Git disponibile. Il log è anche in `audit/results/suite_completa_2026-10-10_followup.log`.

### Suite completa — output integrale

```text
File pytest: 94
........................................................................ [  3%]
..................................................................... [  7%]
...................................................................... [ 10%]
........................................................................ [ 14%]
........................................................................ [ 17%]
........................................................................ [ 21%]
........................................................................ [ 25%]
........................................................................ [ 28%]
........................................................................ [ 32%]
........................................................................ [ 36%]
................................................. [ 38%]
................................................................ [ 41%]
........................................................................ [ 45%]
........................................................................ [ 49%]
........................................................................ [ 52%]
............................................................................................ [ 57%]
.............. [ 58%]
..................................................................... [ 61%]
........................................................................ [ 65%]
........................................................................ [ 69%]
........................................................................ [ 72%]
........................................................................ [ 76%]
................................................................... [ 79%]
........................................................................ [ 83%]
........................................................................ [ 86%]
............................................................. [ 90%]
................................sssss................................... [ 93%]
........................................................................ [ 97%]
....................................................                     [100%]
=============================== warnings summary ===============================
audit/test_elo_w025_confirmation.py::TestPatchGriglia::test_boot_stats_delta_vs_060_con_griglia_ridotta
  /home/user/SoccerMath2.0/audit/grid_search_ensemble_weight.py:224: RuntimeWarning: invalid value encountered in divide
    rr = np.where(staked > 0, prof / staked, np.nan)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
============================= slowest 15 durations =============================
54.81s call     SoccerMath/test_apptest_top_mix.py::TestAppTestCalcolaTopMix::test_a_click_top_mix
44.69s setup    audit/test_bookmaker_source_test.py::TestValutazioneCompleta::test_campioni
44.28s setup    audit/test_bookmaker_source_test.py::TestCopertura::test_b365_avg_max_coprono_tutto
16.39s call     audit/test_ng_regression.py::TestNoExtremeNGRegression::test_all_leagues_no_extreme_ng
13.43s setup    SoccerMath/test_apptest_top_mix.py::TestAppTestCalcolaTopMix::test_a_click_top_mix
12.17s call     audit/test_elo_walker_parity.py::TestProvenienzaFixture::test_v3_fixture_rigenerabile_dal_commit_dichiarato
11.33s setup    audit/test_diagnose_quota_minima.py::TestIntegrazioneReplay::test_bootstrap_punto_in_ci_report_contenuto
8.16s call     audit/test_diagnose_quota_minima.py::TestIntegrazioneReplay::test_tutte_le_quote_usabili_positive
7.88s call     audit/test_diagnose_quota_minima.py::TestIntegrazioneReplay::test_gg_ng_da_btts_1x2_da_csv
7.14s call     SoccerMath/test_basic.py::TestHistoricalBacktest::test_si_testano_le_partite_recenti
6.67s call     SoccerMath/test_season_rosters.py::TestSimulazioneInizioStagione2026::test_tabella_seed_pre_stagione
6.64s setup    SoccerMath/test_topmix_selector_parity.py::TestParitaGriglia::test_1x2_bit_identici_al_fixture_partita_per_partita
6.28s call     SoccerMath/test_basic.py::TestHistoricalBacktest::test_ogni_lega_supportata_produce_righe
4.55s call     audit/test_topmix_margins.py::TestConsistenzaConIlReplayCommittato::test_headline_del_report
4.41s call     SoccerMath/test_apptest_top_mix.py::TestAppTestCalcolaTopMix::test_b_archivio_modello_storico_in_riquadro
1970 passed, 5 skipped, 1 warning, 4773 subtests passed in 366.83s (0:06:06)

--- SoccerMath/test_theme_toggle.py come script ---
2026-10-10 20:32:40.858 WARNING streamlit.runtime.scriptrunner_utils.script_run_context: Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
✅ Run 1 OK - toggle ON (segue tema sistema), nessuna eccezione
✅ Run 2 OK - toggle OFF, CSS light forzato presente (2 blocchi <style>)
✅ Run 3 OK - ritorno a ON, CSS forzato rimosso, nessuna eccezione
✅ Run 4 OK - rerun generico senza crash

🎉 TUTTI I TEST PASSATI: nessun crash in nessuno stato del toggle.

Suite completa exit=0; test_theme_toggle exit=0
```

Esito: **1.970 passed, 5 skipped, 4.773 subtests passed, 1 warning**; exit 0. `SoccerMath/test_theme_toggle.py` eseguito separatamente come script: exit 0.

### Replay `topmix_mercato_v3` — senza `--write`

Comando: `.venv/bin/python audit/replay_topmix_mercato.py --report /tmp/soccermath_topmix_followup/replay_topmix_mercato.md --json /tmp/soccermath_topmix_followup/replay_topmix_mercato.json --righe /tmp/soccermath_topmix_followup/replay_topmix_mercato_rows.csv`. Nessuna rete, nessuna scrittura nel Registro. Log integrale: `audit/results/replay_topmix_mercato_followup.log`.

```text
costruzione del frame (Poisson di produzione + Elo walker + quote)...
frame costruito in 146 s (7347 righe)
# Replay offline del Top Mix di mercato (`topmix_mercato_v3`)

Generato da `audit/replay_topmix_mercato.py` il 2026-10-10T20:35:23Z (commit `cf7346e`, branch `arena/3cf76880-soccermath2-0`). Nessuna rete, nessuna scrittura nel Registro.

Comando: `python audit/replay_topmix_mercato.py`.

## 0. Cosa riproduce

| Elemento | Fonte |
|---|---|
| Quote | CSV storici `SoccerMath/database/*_2024.csv` e `*_2025.csv`, colonne B365H/B365D/B365A (pre-chiusura, come nella PR #49) |
| De-vig | `market_odds.devig_proporzionale` (PRODUZIONE), verificato riga per riga contro le colonne `pre*` della PR #49: scarto massimo 0.00e+00 |
| Scelta | `app.seleziona_riga_top_mix_mercato` (PRODUZIONE): argmax delle probabilita' di mercato, ammissione a 0,55 |
| Segnale "d'accordo" | `market_odds.SOGLIA_ACCORDO` = 0,55, stesso esito (definizione PR #49 §4d) |
| Probabilita' del modello | colonne `m0/m1/m2` del frame PR #49 (blend 0,25 Poisson + 0,75 Elo walker) |
| Campione | 3504 righe (2024/25 + 2025/26, con modello e con terna B365 pre) |

## 1. Confronto con la PR #49

| Voce | Fonte PR #49 | n PR #49 | n replay | Δn | hit PR #49 | hit replay | Δhit | coincide |
|---|---|---|---|---|---|---|---|---|
| scelte_mercato | §4, pooled OOS, mercato B365 pre (prop.) | 1302 | 1302 | +0 | 0.6751 | 0.6751 | +0.0000 | SÌ |
| accordo | §4d tabella B, scelte del modello CON consenso | 1144 | 1144 | +0 | 0.6818 | 0.6818 | +0.0000 | SÌ |
| senza_accordo | §4d tabella B, scelte del modello SENZA consenso | 335 | 335 | +0 | 0.4358 | 0.4358 | +0.0000 | SÌ |

**Esito del confronto: PARITÀ** (tolleranze dichiarate: Δn ≤ 0, |Δhit| ≤ 0.0005).

## 2. Numeri del replay

| Gruppo | n | vinte | hit rate | IC 95% (Wilson) |
|---|---|---|---|---|
| Scelte del mercato (soglia 0,55) | 1302 | 879 | 0.6751 | [0.6492; 0.7000] |
| Scelte del modello CON accordo | 1144 | 780 | 0.6818 | [0.6543; 0.7082] |
| Scelte del modello SENZA accordo | 335 | 146 | 0.4358 | [0.3837; 0.4894] |

Lettura delle scelte di MERCATO separate per accordo (informazione aggiuntiva, non fa parte del confronto con la PR #49):

| Gruppo | n | vinte | hit rate |
|---|---|---|---|
| Scelte del mercato CON accordo del modello | 1144 | 780 | 0.6818 |
| Scelte del mercato SENZA accordo | 158 | 99 | 0.6266 |

## 3. Limiti dichiarati

- Le quote sono quelle dei CSV storici (B365 pre-chiusura), NON quelle dal vivo di The Odds API: il piano gratuito non include lo storico, quindi il replay offline non puo' usare la fonte di produzione.
- La colonna 'fonte' del replay vale `pinnacle` per costruzione (un solo libro, B365): la riserva sulla media dei libri non e' esercitabile sui CSV, che hanno una sola terna per fonte. E' coperta dai test unitari, non da questo replay.
- Il campione e' quello della PR #49 (2024/25 + 2025/26 con modello e terna B365 pre): le righe 2026/27 non hanno quote nei CSV e non entrano.
- L'hit rate del replay non ha intervalli bootstrap a blocchi: usa Wilson, che non tiene conto della correlazione fra partite della stessa giornata. Gli IC della PR #49 sono bootstrap a blocchi e sono quindi piu' larghi.
- Il frame e' messo in cache in audit/output/ (non versionato): con --no-cache viene ricostruito da zero (~2-4 minuti).


json:   /tmp/soccermath_topmix_followup/replay_topmix_mercato.json
righe:  /tmp/soccermath_topmix_followup/replay_topmix_mercato_rows.csv
referto: /tmp/soccermath_topmix_followup/replay_topmix_mercato.md

[esito] parita' con la PR #49: SÌ
```

**Parità verificata:** 1.302 / 1.144 / 335; Δn = +0 per tutte e tre le righe.

### CI GitHub

Esiti **reali** dei controlli GitHub Actions sulla PR #61, commit `4875987ba0c7cd58a379f9abaec1e7891d220d99`:

| Workflow | Esito / durata | Passi eseguiti | Passi saltati |
|---|---|---|---|
| [Suite completa (pytest + test_theme_toggle)](https://github.com/iFelice/SoccerMath2.0/actions/runs/38084464377) | **success**, 5m42s | Setup, checkout con storia completa, controllo filtro documentazione, Python/dipendenze, diagnostica runner, elenco test, suite pytest, `test_theme_toggle.py`, riepilogo, artifact e cleanup. Ogni step concluso `success`. | Nessuno. |
| [Audit Top Mix (sola lettura)](https://github.com/iFelice/SoccerMath2.0/actions/runs/38084464357) | **success**, 4m43s | Checkout, filtro documentazione, setup Python/dipendenze, cartella report, test diagnostici Top Mix/Elo, replay offline `topmix_mercato_v3`, GET JSONBin Schalke–Bayern (sola lettura), ricostruzione, ispezione AST, riepilogo, controllo no-write, pubblicazione artifact e cleanup. Ogni step concluso `success`. | Nessuno. |
| [Replay Top Mix legacy (walk-forward, no-leakage)](https://github.com/iFelice/SoccerMath2.0/actions/runs/38084464398) | **success**, 5s | Setup job e controllo «File rilevanti per il replay»; entrambi `success`. Nessun file rilevante per questo workflow nel diff. | Finestra replay, checkout, Python/dipendenze, secrets, test no-leakage, replay, controlli Registro, riepilogo, verifica no-write e artifact: tutti `skipped` dal filtro. |
| `totals_probe` | **non avviato** | — | Workflow manuale: non eseguito, coerentemente con il vincolo di non lanciare la sonda. |

GitHub ha inoltre emesso annotazioni informative sulla deprecazione Node.js 20 delle actions e sulla futura migrazione di `ubuntu-latest`; non hanno causato errori. Gli esiti qui sopra sono quelli della SHA indicata, prima del commit documentale che aggiunge questa tabella; i controlli sul nuovo HEAD della PR saranno riportati nell'aggiornamento conclusivo senza cambiare le regole preregistrate.

### Non verificato / in attesa

- **Punto 1:** confronto OOS 2017/18–2021/22, coperture, quote invalide, ΔLogLoss/ΔBrier, bootstrap, sensibilità alle quote di chiusura e calibrazione; attende i 25 CSV originali di Felice perché la fonte è irraggiungibile dal sandbox.
- **Punto 4:** nessuna seconda sonda live e nessuna misura di copertura/concordanza della nuova regola; non è disponibile uno snapshot successivo al baseline. Il baseline 10/10 resta escluso e non è stata formulata una conclusione PR #60 dal caso Manchester United–Tottenham.
- Nessuna verifica tramite chiamata a The Odds API (esclusa per vincolo); nessuna valutazione della regola totals sullo snapshot del 10/10.
- Il PR resta aperto e non è stato fatto merge.
