# PR #76 — quattro correzioni totals_mercato_v1

Branch: `arena/a1597864-soccermath2-0`, stessa [PR #76](https://github.com/iFelice/SoccerMath2.0/pull/76), **nessun merge**. Base del diff: `b837823`. Implementazione verificata: `56b5d94`.

## 1. Righe solo O/U

- Pronostico `—`, Modello % `n/d`, Gol piena, Quote %, Quota e Insieme % **stringhe vuote**. Nessuna stima bet365 1X2 viene chiamata per queste righe.
- Ordinamento numerico interno: Quote % 1X2 decrescente, poi solo-O/U in fondo per P O/U non arrotondata decrescente. Una chiave interna non visibile evita di ordinare alfabeticamente la cella Gol o usare il suo arrotondamento.
- In una tabella mista la colonna Quote % viene resa testuale (stessa cifra decimale delle righe 1X2), per rappresentare `""` senza NaN e senza conversioni automatiche di Arrow. Se non ci sono righe solo-O/U, Quote % resta numerica come prima. Il test confronta tutti i campi preesistenti delle righe 1X2 con la funzione a `b837823`.

### Tabella vera da AppTest, stesso snapshot del 16/10

Generata **manualmente**, non durante i test:

```bash
python audit/report_totals_mercato_v1.py --apptest-out audit/results/totals_mercato_v1_correzioni/apptest-table.txt
```

Prezzi e nomi dallo snapshot; come nel primo harness, i kickoff sono traslati nel futuro per non far invecchiare il test. Il calendario e il registro sono simulati. Nessuna scrittura nel registro di produzione.

```text
          Quando                        Partita Pronostico Quote % Modello % Quota            Gol Insieme %
sab 17/10, 03:11     Bayern Munich - RB Leipzig          1    78.6            1,22 Over 2,5 · 85%        70
sab 17/10, 01:11          Real Madrid - Sevilla          1    78.1            1,23 Over 2,5 · 68%        59
sab 17/10, 05:11 Manchester City - Ipswich Town          1    76.9            1,25 Over 2,5 · 69%        59
sab 17/10, 07:11   Hamburger SV - VfB Stuttgart          —               n/d       Over 2,5 · 69%
```

## 2. Origine O/U dedicata

- `ORIGIN_MERCATO_OU = "mercato_ou"`, inserita in `ORIGINI_NOTE` e nelle etichette `Gol (mercato)`, compresa la composizione del registro.
- `entry_registro_totals` usa l'origine dedicata. `resolve_origin`, `origin_from_text` e `origin_of` la riconoscono prima dei fallback Top Mix.
- Le righe della prima PR che hanno ancora `origin=top_mix` ma `selector_version=totals_mercato_v1` si leggono come `mercato_ou`: non occorre migrare o scrivere registri reali. `famiglia_selettore` resta `totals`.
- Backend controllato: `registry_store.field_of` usa la `dedup_key` canonica, senza una whitelist indipendente delle origini. La chiave O/U ha `mercato_ou`, è distinta dalla chiave 1X2 e coincide con quella canonica delle prime righe PR. Test di roundtrip eseguito.
- Il dedup e i conteggi Top Mix escludono l'O/U. Il Registro generale (`righe_visibili`) continua a conservare e mostrare entrambe le famiglie. Replay per chiave `(match_id, variante)`, coverage e Multiple restano invariati aggiungendo la voce O/U della stessa partita, anche quando è una riga legacy PR con origine grezza Top Mix.
- `ultima_registrazione_mercato` filtra Top Mix; `ultima_registrazione_ou` filtra solo `mercato_ou`, con lo stesso formato. Le due frasi condividono una sola lettura del registro.
- Upsert singolo e a blocco: una voce O/U già presente non si duplica e non viene riscritta. Si conserva **l'intero primo record**, anche con nuova probabilità, fonte, congiunta e timestamp. La logica 1X2 resta quella precedente.

## 3. Test senza scritture di file tracciati

- Rimosso dal test O/U il salvataggio di `audit/results/totals_mercato_v1/apptest-table.txt`. La generazione della tabella è ora un'opzione esplicita dello script audit manuale.
- Ricercati gli altri punti di scrittura nei test: gli altri database/CSV/registri di prova usano cartelle temporanee; gli output facoltativi `SCHEDA_RENDER_OUT` e `MULTIPLE_RENDER_OUT` vengono ora dirottati in tempfile se puntano dentro il checkout (anche dopo risoluzione dei symlink).
- Anche la copia temporanea dell'app storica nel test di parità del pulsante è stata spostata da `SoccerMath/_app_pulsante_vecchio.py` a `tempfile.TemporaryDirectory`.
- Il codice e la tabella manuale erano committati **prima** della suite. Tutti i log sono stati scritti fuori dal checkout, in `/home/user/correzioni76`, e copiati qui solo dopo la prova dello stato pulito.

### Prova dopo suite completa e script del tema

```bash
git status --porcelain
```

Output reale: **vuoto, zero byte**, exit code 0. Il file [status-after-suite.txt](totals_mercato_v1_correzioni/status-after-suite.txt) conserva lo stdout vuoto. Nessun reset, ripristino o cancellazione di modifiche è stato eseguito tra suite e questo comando. Anche dopo il giro mirato aggiuntivo lo stato era ancora pulito.

## Impronte Python 3.11, prima e dopo

```text
Python: 3.11.2
1X2 prima: 1d2787b0f45b0f91a6ba651809b6e9ecdb2ba7dec35972dafdb40814186a4bb5
1X2 dopo:  1d2787b0f45b0f91a6ba651809b6e9ecdb2ba7dec35972dafdb40814186a4bb5
IMPRONTE_OU prima: {'totals_mercato_v1': '899c0eb482fb24a97e1e094c6f8313a34d6788f35a117f97ba7ef326b1739b3f'}
IMPRONTE_OU dopo: {'totals_mercato_v1': 'fbb0cb99c42e589c3296a8bc4185c7f5b284bc3d1a67b7e621dabc7517431d8c'}
impronta O/U dopo: fbb0cb99c42e589c3296a8bc4185c7f5b284bc3d1a67b7e621dabc7517431d8c
```

L'impronta **1X2 è identica** a quella richiesta. `SELECTOR_VERSION_CURRENT`, soglia 0,55 e `IMPRONTE` non sono cambiati.

`IMPRONTE_OU["totals_mercato_v1"]` cambia perché `entry_registro_totals`, inclusa nell'impronta autonoma, passa da `origin=ORIGIN_TOP_MIX` a `origin=ORIGIN_MERCATO_OU`. È l'unica funzione del perimetro O/U sotto impronta modificata: **matematica, de-vig, fit, probabilità, soglia 0,67 e selezione O/U invariati**. La versione resta `totals_mercato_v1`: la correzione riguarda la classificazione del record, non un nuovo pronostico o una nuova calibrazione. L'impronta aggiornata mantiene la verifica del codice effettivamente usato.

## Esito dei test nuovi/estesi, per nome

Comando reale, timeout **900 secondi**:

```bash
python -m pytest SoccerMath/test_totals_correzioni.py SoccerMath/test_apptest_totals_mercato.py -v --tb=short -p no:cacheprovider
```

```text
============================= test session starts ==============================
platform linux -- Python 3.11.2, pytest-9.1.1, pluggy-1.7.0 -- /home/user/.venv/bin/python
rootdir: /home/user/SoccerMath2.0
plugins: anyio-4.15.1
collecting ... collected 13 items

SoccerMath/test_totals_correzioni.py::TestOrigineMercatoOU::test_backend_chiave_e_roundtrip_origine_ou PASSED [  7%]
SoccerMath/test_totals_correzioni.py::TestOrigineMercatoOU::test_coverage_dedup_conteggi_topmix_invariati PASSED [ 15%]
SoccerMath/test_totals_correzioni.py::TestOrigineMercatoOU::test_replay_indice_match_variante_non_sovrascrive_1x2 PASSED [ 23%]
SoccerMath/test_totals_correzioni.py::TestOrigineMercatoOU::test_risoluzione_origine_esplicita_label_e_legacy_pr76 PASSED [ 30%]
SoccerMath/test_totals_correzioni.py::TestOrigineMercatoOU::test_upsert_singolo_e_blocco_non_duplicano_ne_sovrascrivono_ou PASSED [ 38%]
SoccerMath/test_totals_correzioni.py::TestLegacyDryRun::test_legacy_compattato_e_grezzo_senza_totals_parita_b837823 PASSED [ 46%]
SoccerMath/test_apptest_totals_mercato.py::TestAppTotals::test_01_tabella_snapshot_e_registro_separato PASSED [ 53%]
SoccerMath/test_apptest_totals_mercato.py::TestAppTotals::test_02_secondo_click_congela_prima_registrazione_ou PASSED [ 61%]
SoccerMath/test_apptest_totals_mercato.py::TestAppTotals::test_03_scheda_partita_sopra_e_sotto_soglia PASSED [ 69%]
SoccerMath/test_apptest_totals_mercato.py::TestAppTotals::test_04_solo_ou_in_fondo_per_probabilita_non_percentuale_arrotondata PASSED [ 76%]
SoccerMath/test_apptest_totals_mercato.py::TestAppTotals::test_05_righe_1x2_identiche_alla_presentazione_b837823 PASSED [ 84%]
SoccerMath/test_apptest_totals_mercato.py::TestAppTotals::test_06_frasi_topmix_e_ou_filtrate_per_origine PASSED [ 92%]
SoccerMath/test_apptest_totals_mercato.py::TestAppTotals::test_07_multiple_liste_conteggi_e_riquadri_invariati_con_ou_nel_registro PASSED [100%]

======================== 13 passed in 110.45s (0:01:50) ========================
```

## Suite completa (tutti i test tracciati)

Elenco: [suite-files.txt](totals_mercato_v1_correzioni/suite-files.txt), **114 file** per pytest. Come la CI, `test_theme_toggle.py` è escluso da pytest ed eseguito come script. Lotto 0: 105 file non-AppTest; lotti 1/2/3: tre file AppTest ciascuno in ordine alfabetico. Comando per ciascun lotto:

```bash
python -m pytest -q -rfE --tb=short -p no:cacheprovider "${FILES[@]}"
```

Ogni invocazione aveva timeout **900 secondi**. Totale: **2.338 passati, 8 skip, 5.994 subtest passati**, nessun errore o fallimento. Il warning è quello preesistente del bootstrap audit con campioni senza puntate, non del modulo O/U.

### Lotto 0 — output completo

```text
..................................................................... [  3%]
..................................................................... [  6%]
...................................................................... [  9%]
........................................................................ [ 12%]
...................................................................... [ 15%]
.................................................................. [ 18%]
........................................................................ [ 21%]
........................................................................ [ 24%]
........................................................................ [ 27%]
........................................................................ [ 31%]
................................................................... [ 34%]
...................................................... [ 36%]
................................................................................................................................ [ 42%]
........................................................................ [ 45%]
........................................................................ [ 48%]
........................................................................ [ 51%]
................................................................................................... [ 55%]
.................................................. [ 58%]
.................................................................................................................... [ 63%]
........................................................................ [ 66%]
...............................................................s........ [ 69%]
........................................................................ [ 72%]
........................................................................ [ 76%]
................................................................... [ 78%]
........................................................................ [ 82%]
........................................................................ [ 85%]
............................................................. [ 88%]
......................sssss.................................................................................. [ 92%]
........................................................................ [ 96%]
........................................................................ [ 99%]
..................                                                       [100%]
=============================== warnings summary ===============================
audit/test_elo_w025_confirmation.py::TestPatchGriglia::test_boot_stats_delta_vs_060_con_griglia_ridotta
  /home/user/SoccerMath2.0/audit/grid_search_ensemble_weight.py:224: RuntimeWarning: invalid value encountered in divide
    rr = np.where(staked > 0, prof / staked, np.nan)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
2259 passed, 6 skipped, 1 warning, 5025 subtests passed in 367.45s (0:06:07)
```

### Lotto 1 — output completo

```text
..........s..... [ 57%]
............                                 [100%]
27 passed, 1 skipped, 156 subtests passed in 126.44s (0:02:06)
```

### Lotto 2 — output completo

```text
.......s........................                                               [100%]
31 passed, 1 skipped, 642 subtests passed in 147.73s (0:02:27)
```

### Lotto 3 — output completo

```text
.....................                         [100%]
21 passed, 171 subtests passed in 123.42s (0:02:03)
```

### test_theme_toggle.py come script

```bash
python SoccerMath/test_theme_toggle.py
```

```text
2026-10-16 15:18:58.911 WARNING streamlit.runtime.scriptrunner_utils.script_run_context: Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
✅ Run 1 OK - toggle ON (segue tema sistema), nessuna eccezione
✅ Run 2 OK - toggle OFF, CSS light forzato presente (2 blocchi <style>)
✅ Run 3 OK - ritorno a ON, CSS forzato rimosso, nessuna eccezione
✅ Run 4 OK - rerun generico senza crash

🎉 TUTTI I TEST PASSATI: nessun crash in nessuno stato del toggle.
```

## 4. Dry-run nuovi e legacy affiancati

Il job PR è offline e senza secret. Restano i nuovi percorsi `totals_snapshot_fixture.py` (snapshot del 16/10 con h2h+totals); sono stati ripristinati **entrambi** i percorsi precedenti: `live_odds_raw_fixtures.py` senza totals e gli snapshot compattati in `audit/data/live_odds_probe`. È ripristinata anche la prova legacy senza bookmaker, oltre a quella nuova.

`--dry-run` **non produce un file**: per verificare il JSON reale si esegue subito dopo il writer con `--fixture`, sempre offline, con destinazione `/tmp`. Il validatore `audit/verifica_quote_legacy.py` richiede `leghe`, confronta esattamente le P 1X2 con writer e matematica a `b837823`, e verifica l'assenza di dati totals/O/U in ogni libro. Non ricorre al vecchio selettore a rete o a probabilità ricopiate. Il checkout CI ha `fetch-depth: 0` per rendere disponibile il commit di riferimento.

Gli snapshot legacy richiesti sono quelli del turno del 10/10 in `live_odds_probe` (i metadati dichiarano acquisizione 08/10); non vengono sostituiti dallo snapshot nuovo. Tutti i nuovi test O/U restano sul 16/10. Nessuna acquisizione o workflow a crediti è stato lanciato; la chiave resta solo nel secret `ODDS_API_KEY`. Nessun replay `--write` e nessun comando di attesa/polling.

### Estratto reale di live_odds.yml

```yaml
      - name: Risposte reali della sonda in forma grezza (0 crediti)
        run: |
          python audit/totals_snapshot_fixture.py --out /tmp/odds_grezze
          python audit/totals_snapshot_fixture.py --out /tmp/odds_senza_bookmakers \
            --senza-bookmakers

      - name: Dry-run sulle risposte reali grezze (nessuna rete, nessuna scrittura)
        working-directory: SoccerMath
        run: |
          set -o pipefail
          python update_live_odds.py \
            --fixture /tmp/odds_grezze \
            --out /tmp/live_odds_dryrun.json \
            --dry-run 2>&1 | tee /tmp/live_odds_dryrun.log
          # Le quote devono esserci: "eventi con almeno un libro=0" significa
          # che la conversione ha perso i bookmaker (guasto del 2026-10-09).
          if grep -q 'eventi con almeno un libro=0' /tmp/live_odds_dryrun.log; then
            echo "::error::la conversione ha perso i bookmaker della risposta reale"
            exit 1
          fi

      # Regressione h2h SENZA totals: entrambi i percorsi precedenti restano.
      - name: Risposte legacy in forma grezza (0 crediti)
        run: |
          python audit/live_odds_raw_fixtures.py --out /tmp/odds_grezze_legacy
          python audit/live_odds_raw_fixtures.py --out /tmp/odds_vuote_legacy --senza-bookmakers

      - name: Dry-run legacy grezzo e verifica probabilità 1X2
        working-directory: SoccerMath
        run: |
          set -o pipefail
          python update_live_odds.py --fixture /tmp/odds_grezze_legacy \
            --out /tmp/live_odds_dryrun_legacy.json --dry-run 2>&1 | tee /tmp/live_odds_legacy.log
          # --dry-run NON scrive: seconda esecuzione sempre offline, solo /tmp,
          # per verificare il JSON realmente prodotto, senza rete o secret.
          python update_live_odds.py --fixture /tmp/odds_grezze_legacy --out /tmp/live_odds_legacy.json
          python ../audit/verifica_quote_legacy.py --file /tmp/live_odds_legacy.json --fixture /tmp/odds_grezze_legacy

      - name: Dry-run sugli snapshot compattati della sonda
        working-directory: SoccerMath
        run: |
          set -o pipefail
          python update_live_odds.py \
            --fixture ../audit/data/live_odds_probe \
            --out /tmp/live_odds_dryrun_compattato.json \
            --dry-run 2>&1 | tee /tmp/live_odds_compattato.log
          python update_live_odds.py --fixture ../audit/data/live_odds_probe --out /tmp/live_odds_compattato.json
          python ../audit/verifica_quote_legacy.py --file /tmp/live_odds_compattato.json --fixture ../audit/data/live_odds_probe

```

### Esecuzione locale degli stessi passi offline

I blocchi `run` del job `dry-run` sono stati estratti dal workflow ed eseguiti localmente (solo esclusa l'installazione dipendenze, già effettuata). Exit code complessivo: **0**. Log completo: [ci-dry-runs.log](totals_mercato_v1_correzioni/ci-dry-runs.log).

Le due verifiche legacy hanno prodotto:

```text
Legacy: leghe=5; eventi=96; P 1X2 identiche a b837823 (differenza=0); nessun dato O/U
Legacy: leghe=5; eventi=96; P 1X2 identiche a b837823 (differenza=0); nessun dato O/U
```

Gli errori `exit 4` nel log sono le prove intenzionali di bookmaker vuoti: entrambe verificano che il file precedente non sia sovrascritto; non sono fallimenti del job. Le scritture offline restano tutte in `/tmp`.

## Diff stat rispetto a b837823

Output reale `git diff b837823 56b5d94 --stat` (commit di implementazione verificato, tabella manuale inclusa; il commit successivo aggiunge soltanto questo referto e i log):

```text
 .github/workflows/live_odds.yml                    |  44 +++++++++
 SoccerMath/app.py                                  |  44 +++++++--
 SoccerMath/prediction_registry.py                  |  31 +++++-
 SoccerMath/registry_composizione.py                |   1 +
 SoccerMath/test_apptest_multiple_riquadri.py       |   5 +
 SoccerMath/test_apptest_scheda_partita.py          |   4 +
 SoccerMath/test_apptest_scheda_pronostici.py       |  11 ++-
 SoccerMath/test_apptest_totals_mercato.py          |  76 +++++++++++++-
 SoccerMath/test_totals_correzioni.py               | 110 +++++++++++++++++++++
 SoccerMath/test_versione_selettore.py              |   2 +-
 audit/report_totals_mercato_v1.py                  |  23 +++++
 .../totals_mercato_v1_correzioni/apptest-table.txt |   5 +
 audit/verifica_quote_legacy.py                     |  53 ++++++++++
 13 files changed, 385 insertions(+), 24 deletions(-)
```

### Diff complessivo (inclusi referto e log)

Output reale di `git diff --cached b837823 --stat` prima del commit delle evidenze:

<!-- stat-start -->
```text
 .github/workflows/live_odds.yml                    |  44 +++
 SoccerMath/app.py                                  |  44 ++-
 SoccerMath/prediction_registry.py                  |  31 +-
 SoccerMath/registry_composizione.py                |   1 +
 SoccerMath/test_apptest_multiple_riquadri.py       |   5 +
 SoccerMath/test_apptest_scheda_partita.py          |   4 +
 SoccerMath/test_apptest_scheda_pronostici.py       |  11 +-
 SoccerMath/test_apptest_totals_mercato.py          |  76 ++++-
 SoccerMath/test_totals_correzioni.py               | 110 +++++++
 SoccerMath/test_versione_selettore.py              |   2 +-
 audit/report_totals_mercato_v1.py                  |  23 ++
 audit/results/totals_mercato_v1_correzioni.md      | 333 +++++++++++++++++++++
 .../totals_mercato_v1_correzioni/apptest-table.txt |   5 +
 .../totals_mercato_v1_correzioni/ci-dry-runs.log   |  88 ++++++
 .../totals_mercato_v1_correzioni/ci-once.json      |   1 +
 .../totals_mercato_v1_correzioni/diff-stat.txt     |  14 +
 .../totals_mercato_v1_correzioni/fingerprints.txt  |   6 +
 .../live-odds-excerpt.yml                          |  48 +++
 .../totals_mercato_v1_correzioni/new-tests.log     |  21 ++
 .../status-after-suite.txt                         |   0
 .../totals_mercato_v1_correzioni/suite-0.log       |  38 +++
 .../totals_mercato_v1_correzioni/suite-1.log       |   3 +
 .../totals_mercato_v1_correzioni/suite-2.log       |   2 +
 .../totals_mercato_v1_correzioni/suite-3.log       |   2 +
 .../totals_mercato_v1_correzioni/suite-files.txt   | 114 +++++++
 .../totals_mercato_v1_correzioni/theme-toggle.log  |   7 +
 audit/verifica_quote_legacy.py                     |  53 ++++
 27 files changed, 1062 insertions(+), 24 deletions(-)
```
<!-- stat-end -->

## CI — una sola osservazione

```bash
gh run list --branch arena/a1597864-soccermath2-0 --limit 20 --json databaseId,workflowName,status,conclusion,headSha,event,url,createdAt
```

Output completo conservato in [ci-once.json](totals_mercato_v1_correzioni/ci-once.json). Alla singola chiamata, dopo il push di `56b5d94`, **non erano ancora elencati run per il nuovo commit**. I quattro run di `b837823` risultavano conclusi con successo: sono del commit precedente, **non costituiscono una CI verde per queste correzioni**. Non sono stati eseguiti attese, polling o altri controlli CI. Nessun workflow è stato lanciato manualmente; su PR Quote live esclude il job a crediti.

La PR #76 è aggiornata sullo stesso branch. Nessun merge.
