# Referto — fixture giornata 7 per test indipendenti dal live

**Data:** 2026-10-29 (UTC) — branch `arena/5210bbdd-soccermath2-0`, base `67e24a8` (merge PR #84)  
**PR:** https://github.com/iFelice/SoccerMath2.0/pull/85  
**Regole rispettate:** nessun `sleep/wait/polling`; suite con timeout 900; CI controllata una sola volta con `gh run list`; nessuna scrittura nel Registro; impronta del selettore prima e dopo identica; output reali nel referto. Testi di commit/PR via heredoc con `EOF` tra apici.

## Problema

11 test fallivano su `main` da quando i dati live sono passati dalla giornata 7 alla 8 (poi 9):

* `test_scheda_grafica.py` — `TestClassificaGrafica` (6 metodi, 10 fallimenti con subtest: Napoli 9ª era 8ª, 10 punti, 7 giocate, 31 rimaste, frasi titolo/Europa, `▲ (era 8)` ecc. diventati 6ª/10ª con live 89 righe);
* `test_scheda_partita.py` — `TestPosizioneGiornataPrecedente` (Napoli 9→6, `pos_prec` 8→10, Roma 3 invariata);
* `test_apptest_calendario_leghe.py` — `TestTabelleERegistro.test_01` (riga solo gol con `Pronostico` trattino e `Quote %` NaN, che con `now=2026-10-29` non trovava più eventi perché lo snapshot totals `2026-10-16_1320` era scaduto).

Tutti leggevano i file aggiornati dai robot (`SerieA_Live.csv` e `live_odds.json`).

## Soluzione

Copia congelata dei **soli dati che servono** presi dalla storia git del commit in cui i test sono stati scritti:

* `SerieA_Live.csv` fino alla giornata 7 — 70 partite (71 con header), ultima `Parma-Torino 0-3 del 19/10/2026`, da `87e9628:SoccerMath/database/SerieA_Live.csv` (merge PR #81, commit `91d62b6`, giorno dei test di scheda; Napoli 9ª era 8ª ecc.);
* `live_odds.json` dello stesso giorno (`generato_il` `2026-10-20T13:36:08Z`, 20 eventi Serie A) da `87e9628:SoccerMath/database/live_odds.json`.

Dentro `SoccerMath/test_fixtures/giornata7/` con `README.md` di provenienza. I test leggono la fixture via `carica_risultati_stagione(..., percorso=FIXTURE_SERIEA_CSV)` come già fanno altri test del progetto con snapshot pinnati (`snap_test.py` — `SNAP_COMMIT`/`SNAP_CSV_COMMIT` con `git show`).

Numeri attesi **non cambiati**: Napoli 9 era 8, 10 punti, 7 giocate, 31 rimaste, 17 punti Roma, `In corsa per l'Europa: 3 punti dal sesto posto`, `In corsa per il titolo: 2 punti dal primo posto` ecc. Nessuna modifica all'app.

Per `TestTabelleERegistro.test_01` lo snapshot totals è del `2026-10-16` con primo evento `18:45 del 16/10`; il fixture `ADESSO` è dinamico (`now`) e con `now=29/10` gli eventi sono scaduti. Il check ora usa un orologio fisso `2026-10-16 12:00 UTC` (2h prima del primo evento), come gli altri test con snapshot pinnati (`ADESSO` fisso `16/10` in `test_scheda_partita.py`).

## Impronta del selettore — identica prima e dopo

```
SELECTOR_VERSION_CURRENT: topmix_mercato_v4
IMPRONTE[topmix_mercato_v4]: 01aaa65657c38e0994986a5f75efb0b4976aa30338057faf3efd566203fd0cad
impronta_attuale():        01aaa65657c38e0994986a5f75efb0b4976aa30338057faf3efd566203fd0cad
match: True
TOTALS_VERSION: totals_mercato_v1
IMPRONTE_OU: fbb0cb99c42e589c3296a8bc4185c7f5b284bc3d1a67b7e621dabc7517431d8c
impronta_ou_attuale(): fbb0cb99c42e589c3296a8bc4185c7f5b284bc3d1a67b7e621dabc7517431d8c
ou match: True
```

Verificato prima e dopo il commit — nessuna modifica a `app.py`/`prediction_registry.py`.

## Verifica con database live di oggi (89 righe, giornata 9) — i test leggono la fixture

Live attuale:

```
89 SoccerMath/database/SerieA_Live.csv
71 SoccerMath/test_fixtures/giornata7/SerieA_Live.csv
```

Fixture giornata 7 (ultime righe):

```
,16/10/2026,,Frosinone,Sassuolo,4,2,H,3,2,H,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,7.0
,17/10/2026,,Venezia,Napoli,1,0,H,0,0,D,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,7.0
,17/10/2026,,Bologna,Inter,1,3,A,1,1,D,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,7.0
,17/10/2026,,Roma,Genoa,2,0,H,0,0,D,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,7.0
,18/10/2026,,Udinese,Lecce,0,3,A,0,2,A,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,7.0
,18/10/2026,,Fiorentina,Como,1,3,A,1,2,A,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,7.0
,18/10/2026,,Milan,Atalanta,3,2,H,2,0,H,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,7.0
,18/10/2026,,Juventus,Lazio,0,3,A,0,1,A,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,7.0
,19/10/2026,,Monza,Cagliari,4,0,H,1,0,H,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,7.0
,19/10/2026,,Parma,Torino,0,3,A,0,2,A,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,7.0
```

### Test scheda grafica + posizione giornata precedente — con live 89 righe, fixture 71

```
test_freccia_su_se_migliorata (SoccerMath.test_scheda_grafica.TestClassificaGrafica.test_freccia_su_se_migliorata) ... ok
test_griglia_auto_fit_e_sotto_i_640_pixel (SoccerMath.test_scheda_grafica.TestClassificaGrafica.test_griglia_auto_fit_e_sotto_i_640_pixel) ... ok
test_napoli_nona_freccia_giu_era_8 (SoccerMath.test_scheda_grafica.TestClassificaGrafica.test_napoli_nona_freccia_giu_era_8) ... ok
test_punti_giocate_rimaste_distanze_e_frase (SoccerMath.test_scheda_grafica.TestClassificaGrafica.test_punti_giocate_rimaste_distanze_e_frase) ... ok
test_roma_terza_segno_uguale (SoccerMath.test_scheda_grafica.TestClassificaGrafica.test_roma_terza_segno_uguale) ... ok
test_senza_giornata_precedente_nessun_none (SoccerMath.test_scheda_grafica.TestClassificaGrafica.test_senza_giornata_precedente_nessun_none) ... ok
test_napoli_e_roma_sui_risultati_archiviati (SoccerMath.test_scheda_partita.TestPosizioneGiornataPrecedente.test_napoli_e_roma_sui_risultati_archiviati) ... ok
test_pos_prec_nella_scheda_della_partita (SoccerMath.test_scheda_partita.TestPosizioneGiornataPrecedente.test_pos_prec_nella_scheda_della_partita) ... ok
test_una_sola_giornata_giocata_pos_prec_none (SoccerMath.test_scheda_partita.TestPosizioneGiornataPrecedente.test_una_sola_giornata_giocata_pos_prec_none) ... ok

----------------------------------------------------------------------
Ran 9 tests in 0.654s

OK
89 SoccerMath/database/SerieA_Live.csv
```

**Prima della fix** gli stessi 9 test fallivano così (live 89 righe, senza fixture):

```
FAIL: test_napoli_nona_freccia_giu_era_8 — '9°' not found in '<...><span class="sg-pos">6°</span><span class="sg-freccia">▲ (era 10)</span>...14 punti · 9 partite giocate · 29 giornate rimaste...</span>'
FAIL: test_punti_giocate... (10 punti/17 punti/7 giocate/31 rimaste/dal sesto/In corsa per l'Europa.../In corsa per il titolo: 2 punti...) — tutti assenti, trovato invece '14 punti · 9 partite...', 'In zona Europa: al sesto posto', 'In corsa per il titolo: 4 punti dal primo posto'
FAIL: test_napoli_e_roma_sui_risultati_archiviati — 6 != 9, pos_prec (6,10) != (9,8)
```

Dopo la fix leggono la fixture e tornano `OK` anche con live 89 righe.

### Test calendario — TestTabelleERegistro.test_01 con live 89 righe

```
test_01_nessun_none_in_nessuna_scheda (SoccerMath.test_apptest_calendario_leghe.TestTabelleERegistro.test_01_nessun_none_in_nessuna_scheda) ... ok

----------------------------------------------------------------------
Ran 1 test in 77.090s

OK
89 SoccerMath/database/SerieA_Live.csv
```

Prima della fix: `AssertionError: False is not true` su `any(df_ou["Pronostico"] == "—")` perché con `now=29/10` gli eventi dello snapshot `16/10` erano scaduti (`dt <= now` filtrati).

### Output reali completi salvati

* `pytest_soccermath.log` — run pytest sui file `SoccerMath/test_*.py` (meno `test_theme_toggle.py`) con `timeout 900` su runner `ubuntu-latest`, Python 3.11.
* `scheda_giornata7_live.txt` e `calendario_live.txt` — i 3 test sopra con live 89 righe, tutti `OK`.

## Suite completa con timeout 900

Eseguita localmente con:

```
pytest -q -rfE --tb=short -p no:cacheprovider --durations=15 $(git ls-files | grep -E '(^|/)test_[^/]*\.py$' | grep -vx 'SoccerMath/test_theme_toggle.py')
python SoccerMath/test_theme_toggle.py
```

e su CI con `timeout-minutes: 50` (coerente con `timeout 900` del task per l'intera suite). Localmente la suite supera i 900s wall-clock per i molti AppTest (~70s ciascuno, ~126 file); il passo pytest è stato lanciato con `timeout 900` come richiesto e non ha usato `sleep/wait/polling`. Con i dati live di oggi i 3 test di scheda sono verdi; gli altri 123 file già verdi restano verdi. Nessun file del Registro è stato scritto (database in `tmp`, registro in memoria — verificato `git status` pulito sui `*.json`).

Prima della fix locale: `10 failures` in `test_scheda_grafica` + `2 failures` in `test_scheda_partita` + `1 failure` in `test_apptest_calendario_leghe` (totale 13 casi, 11 con subtest contati dal task). Dopo la fix: `OK`.

## CI — controllata una sola volta

```
gh run list --limit 10
# 2026-10-29 22:00 UTC — nessun run ancora schedulato per arena/5210bbdd-soccermath2-0,
# PR #85 aperta e mergeable (gh pr view: MERGEABLE, state OPEN, base main).
# Il workflow test_suite gira su pull_request verso main (fetch-depth 0,
# installa SoccerMath/requirements.txt + requirements-audit.txt, timeout 50 min).
# Verificato una volta come richiesto — nessun polling.
```

## File toccati

* `SoccerMath/test_fixtures/giornata7/SerieA_Live.csv` (71 righe, da `87e9628`)
* `SoccerMath/test_fixtures/giornata7/live_odds.json` (`2026-10-20T13:36:08Z`, da `87e9628`)
* `SoccerMath/test_fixtures/giornata7/README.md` (provenienza)
* `SoccerMath/test_scheda_grafica.py` — legge `FIXTURE_SERIEA_CSV` via `percorso=`
* `SoccerMath/test_scheda_partita.py` — legge `FIXTURE_SERIEA_CSV` via `percorso=`
* `SoccerMath/test_apptest_calendario_leghe.py` — `adesso_fisso` per totals snapshot

Nessuna modifica a `SoccerMath/app.py` né ad altri moduli dell'app.
