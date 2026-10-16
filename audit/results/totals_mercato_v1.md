# SoccerMath 2.0 — totals_mercato_v1

## Vincoli e implementazione

- Pronostico aggiuntivo O/U 2,5: **non entra nel selettore 1X2, in Top Mix o nelle Multiple**.
- `SELECTOR_VERSION_CURRENT`, soglia 1X2 0,55 e `IMPRONTE` invariati. Nuova impronta autonoma `IMPRONTE_OU["totals_mercato_v1"]`.
- Writer: `markets=h2h,totals`, `regions=eu`, una chiamata per lega; **2 crediti/chiamata, 10/giro**. Schema v2; tutte le linee ricevute conservate. Il file di produzione attuale non viene riscritto né migrato: v1 senza totals rimane leggibile e non produce O/U.
- Matematica copiata in `SoccerMath/totals_mercato.py`: nessun import di produzione da `audit/`. Linee mezze, intere e a quarti, fit Dixon–Coles, rifiuto del fit non convergente/non finito o con residuo massimo > 1e-5.
- Pinnacle con terna valida e linea valida più bassa; in assenza di totals Pinnacle validi, mediana delle P Over 2,5 de-vigate di almeno tre bookmaker distinti, con la terna Pinnacle oppure la riserva 1X2 già esistente. Quote invalide non diventano probabilità.
- `SOGLIA_OU = 0.67`. Congiunta dal riquadro della griglia, mai dal prodotto; assente senza entrambe le scelte. Nessuna cella nuova contiene None/nan/NaN.
- Pronostici: unione per partita delle scelte 1X2 e O/U; Gol e Insieme % sono celle testuali. `Modello %` resta riferito all'1X2 se presente; per una riga solo O/U è `n/d`. Caption e scheda partita dichiarano `n/d` per il modello gol non validato. Pareggi e Multiple mantengono le proprie colonne.
- Registro: righe autonome `OVER_2.5` / `UNDER_2.5`, versione O/U, probabilità non arrotondata e prima probabilità di mercato, fonte, linea Pinnacle e congiunta se disponibile. La prima riga O/U viene congelata integralmente, anche con prezzi diversi al secondo clic. Famiglia `totals` separata: nessuna contaminazione di conteggi, frase e rinfresco 1X2; frase d'esito Gol separata nello stesso formato. Un solo salvataggio del registro per clic.
- Nessuna chiamata a The Odds API, nessun workflow a crediti lanciato, nessun replay `--write`. Nessun comando di attesa/polling. La chiave non è stata letta o riprodotta: resta solo nel secret `ODDS_API_KEY`.

## Impronte prima/dopo (Python 3.11)

Output reale; la riga iniziale è stata acquisita prima di modificare il codice:

```
Python 3.11.2
1X2 prima: 1d2787b0f45b0f91a6ba651809b6e9ecdb2ba7dec35972dafdb40814186a4bb5
1X2 dopo:  1d2787b0f45b0f91a6ba651809b6e9ecdb2ba7dec35972dafdb40814186a4bb5
Identiche: True
O/U: 899c0eb482fb24a97e1e094c6f8313a34d6788f35a117f97ba7ef326b1739b3f
```

## Suite completa

Stesso insieme della CI: file `test_*.py` tracciati più i due nuovi test, escluso `test_theme_toggle.py` (eseguito come script). Elenco completo: [suite-files.txt](totals_mercato_v1/suite-files.txt), **113 file**, quattro lotti. Comando per ciascuno (timeout dell'invocazione **900 s**):

```bash
python -m pytest -q -rfE --tb=short -p no:cacheprovider "${FILES[@]}"
```

Lotto 0: 104 file non-AppTest. Lotti 1/2/3: tre file AppTest ciascuno, in ordine alfabetico nell'elenco. Totale: **2.328 passati, 8 skip, 5.994 subtest passati**, nessun errore o fallimento. Un warning numerico nell'audit del bootstrap (divisione con campioni senza puntate), non nel modulo O/U. Tutte le invocazioni entro 900 secondi.

Nota di ambiente: il primo passaggio ha rilevato la storia git incompleta; eseguito `git fetch --unshallow origin` senza cambiare branch, quindi rieseguiti **tutti** i lotti. Gli output sotto sono quelli finali. I test preesistenti conservano le loro fixture offline/storiche; quelli O/U e il dry-run CI usano lo snapshot del 16/10. Lo smoke test del tema è stato reso offline con lo stesso snapshot e calendario simulato vuoto.

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
................................................................................................... [ 56%]
.................................................. [ 58%]
............................................ [ 60%]
........................................................................ [ 63%]
........................................................................ [ 66%]
.........................................................s.............. [ 69%]
........................................................................ [ 73%]
........................................................................ [ 76%]
................................................................... [ 79%]
........................................................................ [ 82%]
........................................................................ [ 85%]
............................................................. [ 88%]
................sssss........................................................................................ [ 93%]
........................................................................ [ 96%]
........................................................................ [ 99%]
............                                                             [100%]
=============================== warnings summary ===============================
audit/test_elo_w025_confirmation.py::TestPatchGriglia::test_boot_stats_delta_vs_060_con_griglia_ridotta
  /home/user/SoccerMath2.0/audit/grid_search_ensemble_weight.py:224: RuntimeWarning: invalid value encountered in divide
    rr = np.where(staked > 0, prof / staked, np.nan)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
2253 passed, 6 skipped, 1 warning, 5025 subtests passed in 269.14s (0:04:29)
```

### Lotto 1 — output completo

```text
..........s..... [ 57%]
............                                 [100%]
27 passed, 1 skipped, 156 subtests passed in 101.95s (0:01:41)
```

### Lotto 2 — output completo

```text
.......s........................                                               [100%]
31 passed, 1 skipped, 642 subtests passed in 120.26s (0:02:00)
```

### Lotto 3 — output completo

```text
.................                             [100%]
17 passed, 171 subtests passed in 104.53s (0:01:44)
```

### Parità e retrocompatibilità — output dedicato

```
test_congiunta_e_riquadro_non_prodotto (test_totals_mercato.TestTotalsMercato.test_congiunta_e_riquadro_non_prodotto) ... ok
test_legacy_senza_totals_si_legge_senza_ou (test_totals_mercato.TestTotalsMercato.test_legacy_senza_totals_si_legge_senza_ou) ... ok
test_linee_intere_mezze_quarti (test_totals_mercato.TestTotalsMercato.test_linee_intere_mezze_quarti) ... ok
test_parita_snapshot_tutti_gli_eventi_fittabili (test_totals_mercato.TestTotalsMercato.test_parita_snapshot_tutti_gli_eventi_fittabili) ... ok
test_primaria_linea_piu_bassa_valida (test_totals_mercato.TestTotalsMercato.test_primaria_linea_piu_bassa_valida) ... ok
test_riserva_mediana_minimo_tre_e_terna_di_riserva (test_totals_mercato.TestTotalsMercato.test_riserva_mediana_minimo_tre_e_terna_di_riserva) ... ok
test_soglia_e_celle_senza_non_numeri (test_totals_mercato.TestTotalsMercato.test_soglia_e_celle_senza_non_numeri) ... ok
test_writer_conserva_tutte_le_linee_e_totals_senza_h2h (test_totals_mercato.TestTotalsMercato.test_writer_conserva_tutte_le_linee_e_totals_senza_h2h) ... ok

----------------------------------------------------------------------
Ran 8 tests in 2.936s

OK
Parità snapshot: 97 eventi, tolleranza 1e-9
```

### test_theme_toggle.py come script

```bash
python SoccerMath/test_theme_toggle.py
```

```text
2026-10-16 14:08:54.556 WARNING streamlit.runtime.scriptrunner_utils.script_run_context: Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
✅ Run 1 OK - toggle ON (segue tema sistema), nessuna eccezione
✅ Run 2 OK - toggle OFF, CSS light forzato presente (2 blocchi <style>)
✅ Run 3 OK - ritorno a ON, CSS forzato rimosso, nessuna eccezione
✅ Run 4 OK - rerun generico senza crash

🎉 TUTTI I TEST PASSATI: nessun crash in nessuno stato del toggle.
```

### Writer reale, snapshot 16/10, dry-run senza scrittura

```bash
python audit/totals_snapshot_fixture.py --out /home/user/totals-raw
python SoccerMath/update_live_odds.py --fixture /home/user/totals-raw --out /home/user/totals-dry-run.json --dry-run
```

```text
INFO soccer_italy_serie_a: eventi=20, eventi con almeno un libro=20, eventi con Pinnacle=20, bookmaker nella risposta grezza=398 (distinti=24), mercati grezzi: h2h=398, totals=398 - OK
INFO soccer_epl: eventi=20, eventi con almeno un libro=20, eventi con Pinnacle=20, bookmaker nella risposta grezza=429 (distinti=25), mercati grezzi: h2h=429, totals=429 - OK
INFO soccer_spain_la_liga: eventi=21, eventi con almeno un libro=21, eventi con Pinnacle=21, bookmaker nella risposta grezza=381 (distinti=21), mercati grezzi: h2h=381, totals=381 - OK
INFO soccer_germany_bundesliga: eventi=18, eventi con almeno un libro=18, eventi con Pinnacle=18, bookmaker nella risposta grezza=341 (distinti=22), mercati grezzi: h2h=341, totals=341 - OK
INFO soccer_france_ligue_one: eventi=18, eventi con almeno un libro=18, eventi con Pinnacle=18, bookmaker nella risposta grezza=333 (distinti=22), mercati grezzi: h2h=333, totals=333 - OK
INFO Giro completo: 5/5 leghe con eventi, 5/5 leghe con quote, 97 eventi totali, 97 eventi con almeno un libro, 97 con Pinnacle, 1882 libri in tutto.
INFO Crediti: usati None, residui None, costo ultima chiamata None (quota 500/mese).
INFO dry-run: /home/user/totals-dry-run.json NON scritto (97 eventi sarebbero stati scritti).
```

Gli header crediti non sono simulati: `None` nel log del writer significa header assenti nella fixture ricostruita, non una cella dell'interfaccia. Rete e consumo crediti: zero. L'unione restituisce 1.882 libri contro 1.881 del solo h2h perché conserva anche un libro totals senza terna.

## Snapshot: tutti i pronostici O/U nei sette giorni

Fonte: `audit/data/totals_probe/2026-10-16_1320`, unione h2h pinnato e totals grezzi per id evento e chiave bookmaker, senza altre acquisizioni. La finestra parte dall'istante della sonda totals, estremo destro escluso. La P 1X2 è quella non arrotondata del selettore reale, estratto via AST dal codice di produzione (non riscritto).

Comando riproducibile, nessuna rete:

```bash
python audit/report_totals_mercato_v1.py
```

Finestra UTC: [2026-10-16T13:20:26+00:00, 2026-10-23T13:20:26+00:00)
Eventi fittabili: 97; nella finestra: 49; O/U >= 0.67: 9

| Partita | Fonte | Linea Pinnacle | P Over 2,5 | P Under 2,5 | 1X2 | P 1X2 | P congiunta |
|---|---|---:|---:|---:|:---:|---:|---:|
| Manchester City–Ipswich Town | pinnacle_linea_3.5 | 3.5 | 69.160515872% | 30.839484128% | 1 | 76.870024303% | 58.546386319% |
| Real Betis–Barcelona | pinnacle_linea_3.75 | 3.75 | 76.939345352% | 23.060654648% | 2 | 68.345716602% | 57.120765388% |
| Real Madrid–Sevilla | pinnacle_linea_3.25 | 3.25 | 68.215662632% | 31.784337368% | 1 | 78.128746801% | 58.962342881% |
| Eintracht Frankfurt–1. FC Köln | pinnacle_linea_3.5 | 3.5 | 73.137094565% | 26.862905435% | — | — | — |
| Elversberg–Augsburg | pinnacle_linea_3.25 | 3.25 | 67.085124145% | 32.914875855% | — | — | — |
| Hamburger SV–VfB Stuttgart | pinnacle_linea_3.5 | 3.5 | 69.282389789% | 30.717610211% | — | — | — |
| Bayern Munich–RB Leipzig | pinnacle_linea_4.5 | 4.5 | 85.103145729% | 14.896854271% | 1 | 78.621447753% | 70.356640510% |
| Borussia Monchengladbach–TSG Hoffenheim | pinnacle_linea_3.5 | 3.5 | 69.170008654% | 30.829991346% | — | — | — |
| Strasbourg–Paris Saint Germain | pinnacle_linea_3.5 | 3.5 | 71.503696585% | 28.496303415% | 2 | 68.707899571% | 54.309785381% |

## Tre partite richieste (a parte)

| Partita | Fonte | Linea Pinnacle | P Over 2,5 | P Under 2,5 | 1X2 | P 1X2 | P congiunta |
|---|---|---:|---:|---:|:---:|---:|---:|
| Real Madrid–Sevilla | pinnacle_linea_3.25 | 3.25 | 68.215662632% | 31.784337368% | 1 | 78.128746801% | 58.962342881% |
| Bayern Munich–RB Leipzig | pinnacle_linea_4.5 | 4.5 | 85.103145729% | 14.896854271% | 1 | 78.621447753% | 70.356640510% |
| Manchester City–Ipswich Town | pinnacle_linea_3.5 | 3.5 | 69.160515872% | 30.839484128% | 1 | 76.870024303% | 58.546386319% |


Le righe senza 1X2 non espongono una congiunta anche se la griglia consente di calcolarne una: non c'è il secondo pronostico mostrato. Nella finestra tutte le nove scelte sono Over; nessun Under supera 0,67. Le linee a 3,25/3,75/4,5 non vengono confuse con la probabilità Over 2,5: si esegue prima il fit sulla linea effettiva, poi si legge il riquadro >2,5.

## Colonne reali da AppTest

Output di `TestAppTotals.test_01_tabella_snapshot_e_registro_separato`, raccolto dal DataFrame reso dall'app, non ricostruito nel referto. Per tenere il test valido nel futuro i kickoff sono riposizionati relativamente all'orologio; nomi e prezzi sono quelli dello snapshot. Calendario/storage/rete simulati dal harness, nessun registro reale toccato. Il quinto evento (Everton–Chelsea) non compare nella tabella perché non ha né 1X2 né O/U sopra soglia; la scheda ne mostra comunque P(Over 2,5) senza pronostico.

```text
          Quando                        Partita Pronostico  Quote % Modello % Quota            Gol Insieme %
sab 17/10, 02:11     Bayern Munich - RB Leipzig          1     78.6            1,22 Over 2,5 · 85%        70
sab 17/10, 00:11          Real Madrid - Sevilla          1     78.1            1,23 Over 2,5 · 68%        59
sab 17/10, 04:11 Manchester City - Ipswich Town          1     76.9            1,25 Over 2,5 · 69%        59
sab 17/10, 06:11   Hamburger SV - VfB Stuttgart          —     69.3       n/d  1,39 Over 2,5 · 69%
```

Il test successivo cambia i prezzi e verifica che le quattro righe O/U già registrate rimangano identiche. Il test scheda verifica la frase Gol sopra e sotto soglia. `test_05_mai_none_nan_in_nessuna_tabella_dell_app` controlla sia le nuove colonne legacy vuote sia tutte le nuove celle non vuote dello snapshot, comprese righe solo O/U.

## Diff stat

Output di `git diff --cached --stat` sui file di implementazione, test e generatori (referto e log esclusi):

```text
 .github/workflows/live_odds.yml              |  29 +--
 SoccerMath/app.py                            | 112 +++++++++-
 SoccerMath/market_odds.py                    |   2 +-
 SoccerMath/prediction_registry.py            |   2 +
 SoccerMath/scheda_partita.py                 |  12 +
 SoccerMath/test_apptest_scheda_pronostici.py |   9 +-
 SoccerMath/test_apptest_selezione_tabelle.py |  20 ++
 SoccerMath/test_apptest_totals_mercato.py    | 104 +++++++++
 SoccerMath/test_problemi_produzione.py       |   2 +-
 SoccerMath/test_tabelle_sigle_percentuali.py |   2 +-
 SoccerMath/test_theme_toggle.py              |  17 +-
 SoccerMath/test_totals_mercato.py            | 135 ++++++++++++
 SoccerMath/test_update_live_odds.py          |   4 +-
 SoccerMath/test_versione_selettore.py        |  22 ++
 SoccerMath/totals_mercato.py                 | 317 +++++++++++++++++++++++++++
 SoccerMath/update_live_odds.py               |  45 ++--
 audit/report_totals_mercato_v1.py            |  74 +++++++
 audit/totals_snapshot_fixture.py             |  62 ++++++
 18 files changed, 920 insertions(+), 50 deletions(-)
```

## CI e PR

La singola osservazione CI sarà acquisita dopo il push e l’apertura della PR, senza attese o polling.

Nessun merge eseguito o richiesto.
