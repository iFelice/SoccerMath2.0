# Referto — fixture `SerieA_Live.csv` per gli AppTest della scheda + censimento dati volatili

- **Data**: 2026-11-02 (UTC)
- **Branch**: `arena/4a6ee9b6-soccermath2-0`, partito da `1873c17 Auto-update live data 2026-11-02T02:55Z` (= `main`/`origin/main`)
- **PR**: https://github.com/iFelice/SoccerMath2.0/pull/89
- **Ambiente locale**: `/tmp/smvenv/bin/python` (Python 3.11, `SoccerMath/requirements.txt` + `requirements-audit.txt` + `pytest` 9.2.0 + `pytest-xdist` 3.8.0). Storia git completa (918 commit dopo `git fetch --unshallow origin main`).
- **Regole rispettate**: nessun comando di attesa/polling; suite con `timeout 900`; CI controllata **una sola volta** con `gh run list`; nessuna scrittura nel Registro; testi di commit e PR scritti con file/heredoc `<<'EOF'`; nessuna asserzione cambiata; nessuna modifica all'app; **nessuno dei test censiti al punto 2 e' stato corretto**.

---

## 1. Punto 1 — diagnosi e correzione

### Perche' il test era rosso

`SoccerMath/test_apptest_navigazione.py::_BaseAppTest.setUpClass` crea una cartella
temporanea e vi **linka** tutti i file del database reale (`_link_del_database`), poi
patcha `config.DATABASE_DIR`, `PREDICTIONS_FILE`, l'orologio e il Registro. Il link
per `SerieA_Live.csv` punta quindi a `SoccerMath/database/SerieA_Live.csv`, che i
robot riscrivono a ogni giornata.

Stato del database **live di oggi 2026-11-02** (usato per la verifica, NON modificato):

```
wc -l SoccerMath/database/*_Live.csv
   73 SoccerMath/database/Bundesliga_Live.csv
  109 SoccerMath/database/LaLiga_Live.csv
   81 SoccerMath/database/Ligue1_Live.csv
   90 SoccerMath/database/Premier_Live.csv
   99 SoccerMath/database/SerieA_Live.csv
  452 total
```

`SerieA_Live.csv` = 98 partite, ultima riga del 01/11/2026 (giornata 10). Classifica:

| | live 02/11 (98 partite) | congelata giornata 7 (70 partite) |
|---|---|---|
| 1ª | **Lazio** 28 punti, 10 giocate, `pos_prec=2` | **Inter** 19 punti, 7 giocate, `pos_prec=1` |
| 2ª | **Inter** 25 punti, 10 giocate, `pos_prec=1` | **Lazio** 19 punti, 7 giocate, `pos_prec=2` |
| 3ª | Roma 24, 10, 3 | Roma 17, 7, 3 |
| 4ª | Como 23, 10, 4 | Milan 15, 7, 5 |

L'asserzione a riga 515 commenta `# Inter e' prima`:

```python
self.assertIn("Al comando della classifica", testo)  # Inter e' prima
```

Con la Lazio prima, la frase non viene piu' generata.

`live_odds.json` in produzione al momento della verifica:
`generato_il: 2026-11-01T15:15:10Z`, `schema: soccermath_live_odds_v2`,
`n_eventi: 63` (Serie A 14, Premier League 13, La Liga 13, Bundesliga 10, Ligue 1 13).

### Il dettaglio non ovvio

Una prova empirica ha mostrato che **sostituire il symlink nella cartella temporanea
con la copia congelata non basta**, e nemmeno patchare `config.DATABASE_DIR`:

```
percorso_live_csv("Serie A") -> /home/user/SoccerMath2.0/SoccerMath/database/SerieA_Live.csv
patch solo DATABASE_DIR      -> stesso percorso assoluto, 98 righe, Lazio prima
symlink -> copia congelata    -> stesso percorso assoluto, 98 righe, Lazio prima
patch LEAGUES_CONFIG[...]     -> /tmp/sm_apptest_nav_*/SerieA_Live.csv, 70 righe, Inter prima
```

`config.py` salva `LEAGUES_CONFIG["Serie A"]["live_csv"]` come **percorso assoluto
all'import**; `scheda_partita.percorso_live_csv()` legge quel valore, e
`app.py:3802` / `app.py:4204` chiamano `carica_risultati_stagione(CAMP)` senza
`percorso`. Serve quindi ripuntare anche `LEAGUES_CONFIG`.

### La modifica

Un solo file, `SoccerMath/test_apptest_scheda_partita.py`; `_BaseScheda.setUpClass`
chiama `super().setUpClass()`, rimuove il link `SerieA_Live.csv` dalla cartella
temporanea, vi copia `test_fixtures/giornata7/SerieA_Live.csv` (la stessa fixture
congelata della PR #85 usata da `test_scheda_partita.py` e
`test_scheda_grafica.py`) e registra in `cls._patches` un
`mock.patch.dict(config.LEAGUES_CONFIG["Serie A"], {"live_csv": <tmp>})`, cosi' la
`tearDownClass` della fixture comune ripristina la configurazione.

```diff
$ git diff --stat
 SoccerMath/test_apptest_scheda_partita.py | 38 ++++++++++++++++++++++++++++++-
 1 file changed, 37 insertions(+), 1 deletion(-)

$ git diff -U0 | grep -E "^[+-].*assert" || echo "NESSUNA asserzione aggiunta/rimossa"
NESSUNA asserzione aggiunta/rimossa
```

```diff
--- a/SoccerMath/test_apptest_scheda_partita.py
+++ b/SoccerMath/test_apptest_scheda_partita.py
@@ -102,7 +102,43 @@ def _titolo_atteso(casa: str, trasferta: str) -> str:
 class _BaseScheda(_BaseAppTest):
-    """Fixture comune piu' il calendario della giornata per la scheda Partite."""
+    """Fixture comune piu' il calendario della giornata per la scheda Partite.
+
+    Nella cartella temporanea il ``SerieA_Live.csv`` NON e' il collegamento al
+    file live (che i robot riscrivono a ogni giornata): e' la COPIA CONGELATA
+    della giornata 7 di ``test_fixtures/giornata7`` (PR #85), la stessa che
+    usano ``test_scheda_partita.py`` e ``test_scheda_grafica.py``. In quella
+    classifica l'Inter e' prima, quindi la frase attesa della scheda
+    Bologna-Inter («Al comando della classifica») resta stabile.
+    """
+
+    #: 70 partite, ultima Parma-Torino 0-3 del 19/10/2026 (giornata 7).
+    FIXTURE_SERIEA_LIVE = os.path.join(HERE, "test_fixtures", "giornata7",
+                                       "SerieA_Live.csv")
+
+    @classmethod
+    def setUpClass(cls):
+        super().setUpClass()
+        import shutil
+        from unittest import mock
+        import config
+
+        destinazione = cls.tmp / "SerieA_Live.csv"
+        destinazione.unlink(missing_ok=True)
+        shutil.copy2(cls.FIXTURE_SERIEA_LIVE, destinazione)
+
+        ripuntato = mock.patch.dict(
+            config.LEAGUES_CONFIG["Serie A"], {"live_csv": str(destinazione)})
+        ripuntato.start()
+        cls._patches.append(ripuntato)
```

Nessun file di `SoccerMath/database/`, nessuna riga di `app.py`, nessuna asserzione
e nessun test del punto 2 sono stati toccati.

---

## 2. Verifica del punto 1 con il database live di oggi

Comando (eseguito due volte: prima e dopo la correzione, sempre con il database
live del 02/11/2026 sul disco):

```
STREAMLIT_BROWSER_GATHER_USAGE_STATS=false timeout 900 /tmp/smvenv/bin/python -m pytest \
  -q -rfE --tb=short -p no:cacheprovider \
  "SoccerMath/test_apptest_scheda_partita.py::TestSchedaPartitaAppTest::test_03_la_riga_apre_la_scheda_della_partita_giusta"
```

**PRIMA della correzione** — output reale (`/tmp/pre_fix_test03.log`, `--tb=long`), exit 1:

```
>               self.assertIn("Al comando della classifica", testo)  # Inter e' prima
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E               AssertionError: 'Al comando della classifica' not found in '### Bologna - Inter
                  ...
                  <li>Bologna - Inter 1-3 il 17/10 (giornata 7)</li> ...'
SoccerMath/test_apptest_scheda_partita.py:515: AssertionError
=========================== short test summary info ============================
SUBFAILED(riga=2) SoccerMath/test_apptest_scheda_partita.py::TestSchedaPartitaAppTest::test_03_la_riga_apre_la_scheda_della_partita_giusta
1 failed, 1 passed, 2 subtests passed in 139.40s (0:02:19)
```

Nel testo reso si legge `10 partite` e `In stagione: ... (10 partite)`: conferma che
l'app stava leggendo il CSV live a 98 righe, non la copia congelata.

**DOPO la correzione** — output reale (`/tmp/post_fix_test03.log`), con lo stesso
database live sul disco:

```
$ ... ; echo "EXIT=$?" ; tail -6 /tmp/post_fix_test03.log
EXIT=0
.                                                                     [100%]
1 passed, 3 subtests passed in 126.45s (0:02:06)
```

**Classe sorella** che eredita `_BaseScheda` (`/tmp/post_fix_grafica.log`), per
verificare che il ripuntamento non rompa gli altri AppTest della scheda:

```
$ STREAMLIT_BROWSER_GATHER_USAGE_STATS=false timeout 900 /tmp/smvenv/bin/python -m pytest \
    -q -rfE --tb=short -p no:cacheprovider SoccerMath/test_apptest_scheda_grafica.py
EXIT=0
....                                             [100%]
4 passed, 24 subtests passed in 166.69s (0:02:46)
```

I warning di contesto (`missing ScriptRunContext`, `quote OBSOLETE, eta' 121.1 h`,
`SSLError` su `api.football-data.org`, nomi sconosciuti nei roster) compaiono in
entrambi i run e non sono la causa del fallimento: l'AppTest e' offline per
costruzione.

---

## 3. Impronta del selettore: prima e dopo

`SoccerMath/test_versione_selettore.py` (`impronta_attuale()`,
`impronta_ou_attuale()`, `IMPRONTE`, `IMPRONTE_OU`):

| | prima | dopo |
|---|---|---|
| `SELECTOR_VERSION_CURRENT` | `topmix_mercato_v4` | `topmix_mercato_v4` |
| `impronta_attuale()` | `01aaa65657c38e0994986a5f75efb0b4976aa30338057faf3efd566203fd0cad` | `01aaa65657c38e0994986a5f75efb0b4976aa30338057faf3efd566203fd0cad` |
| `impronta_ou_attuale()` | `fbb0cb99c42e589c3296a8bc4185c7f5b284bc3d1a67b7e621dabc7517431d8c` | `fbb0cb99c42e589c3296a8bc4185c7f5b284bc3d1a67b7e621dabc7517431d8c` |

Output reale del ricontrollo finale, **dopo** la modifica e dopo la suite completa:

```
SELECTOR_VERSION_CURRENT: topmix_mercato_v4
impronta del selettore DOPO: 01aaa65657c38e0994986a5f75efb0b4976aa30338057faf3efd566203fd0cad
impronta OU DOPO: fbb0cb99c42e589c3296a8bc4185c7f5b284bc3d1a67b7e621dabc7517431d8c
identiche alle costanti: True True
```

**Le impronte sono identiche** e coincidono con le costanti di riferimento. Nessun
file del selettore e' stato modificato.

---

## 4. Punto 2 — censimento dei test che dipendono ancora da dati che cambiano da soli

**Popolazione esaminata**: tutti i **128 file `test_*.py` tracciati** da
`git ls-files | grep -E '(^|/)test_[^/]*\.py$'` (127 passati a pytest +
`SoccerMath/test_theme_toggle.py` eseguito come script). Raccolta: `2571 tests
collected in 32.70s`. Cercati: letture da disco di `SoccerMath/database`
(`*_Live.csv`, `live_odds.json`, archivi xG, `season_rosters.json`),
`datetime.now()` non congelato, e asserzioni su classifica, punti, giornate,
partite future. **Nessuno di questi test e' stato corretto.**

### 4a. CSV / quote lette dal disco con asserzioni su valori mutevoli

| # | File | Test | Dato che legge | Asserzione a rischio | Stima di quando si rompe |
|---|---|---|---|---|---|
| 1 | `SoccerMath/test_apptest_calendario_leghe.py` | `TestCalendarioDellaScheda::test_01_ogni_lega_ha_il_suo_calendario` (righe 298-302) | `_BaseQuoteFinte._link_del_database()` crea symlink a **tutti** i CSV reali, in particolare `Bundesliga_Live.csv` (73 righe oggi); l'orologio del fixture e' `datetime.now()` reale | `assertRegex(testo, r"\d+°")`, `assertNotIn("Bayern: dati di classifica insufficienti", testo)`, stessa per Dortmund: posizione/classifica sufficiente di due squadre | Al primo `update_database` (cron `0 */6 * * *`) che riscriva il CSV Bundesliga senza abbastanza partite di Bayern/Dortmund; con certezza al **rollover 01/07/2027**, quando i `*_Live.csv` vengono archiviati/svuotati e la classifica sparisce |
| 2 | `SoccerMath/test_basic.py` | `TestHistoricalBacktest::{test_finestra_non_oltre_max_test, test_si_testano_le_partite_recenti, test_non_sembra_il_tifo_della_domenicale, test_ogni_lega_supportata_produce_righe}`; `TestLeagueEngineDedupe::test_nessuna_partita_duplicata` | `get_league_db_files` / `get_league_engine` / `run_historical_backtest` leggono tutti i CSV da `config.DATABASE_DIR`, **compresi i 5 `*_Live.csv`** (452 righe oggi) | `assertGreaterEqual(len(self.df), 250)` e `assertLessEqual(..., 300)` (oggi 300); `poisson_ok.mean()` dentro `(0.40, 0.90)` (misurato **0.5767**); `assertGreater(len(df), 100)` per ogni lega; `assertEqual(len(win), 50)`; `assertEqual(int(dup), 0)` | La media `poisson_ok` e' calcolata su risultati che cambiano: puo' uscire dalla banda **gia' alle prossime giornate di novembre 2026** (ogni turno aggiunge ~10 righe per lega). `>= 250`, `> 100` e `len(win)==50` saltano al **rollover 01/07/2027** con i Live azzerati; `dup==0` salta se un robot riscrive una riga duplicata (ogni 6 h) |
| 3 | `SoccerMath/test_season_rosters.py` | `TestSimulazioneInizioStagione2026::{test_serie_a, test_premier_league, test_la_liga, test_bundesliga, test_ligue_1, test_tabella_seed_pre_stagione}` (righe 305-338); `TestFileReale::test_copertura_e_taglie` | `_DBTemp` **copia tutti i CSV reali** da `DATABASE_DIR`; `_giornata1()` legge `<Lega>_Live.csv` e prende `Matchday == min()` (prima giornata) | Liste fisse di promosse: `assertEqual(entranti, ["Frosinone","Monza","Venezia"])`, `["Coventry City","Hull City","Ipswich"]`, `["Deportivo","Málaga","Santander"]`, `["Elversberg","SC Paderborn","Schalke 04"]`, `["Le Mans","Troyes"]`; `assertEqual(n, 10)` / `9` partite della prima giornata; `assertEqual(len(righe), 3+3+3+3+2)` | **Rollover 01/07/2027**: il Live contiene la stagione 2027/28, nuove promosse e un'altra prima giornata → tutte le liste e i conteggi cambiano. Prima ancora se il robot riscrive/corregge le righe della giornata 1 |
| 4 | `SoccerMath/test_season_rosters.py` | `TestValidazioneETolleranza::test_file_reale_valido_oltre_il_termine` (476-482); `TestControlloLiveCsv::{test_database_reale_senza_date_future_ne_coppie_ripetute, test_eri_e_oggi_non_sono_futuri, test_eri_non_diventa_futura_se_l_orologio_ha_un_giorno_di_scarto, test_al_bordo_della_tolleranza_e_appena_oltre, test_data_futura_e_errore}` (570-718) | `SR.validate_live_csvs()` **senza `now`** → `datetime.now(timezone.utc)` REALE (il docstring dice esplicitamente che l'orologio di produzione NON va fermato), sui 5 `*_Live.csv` reali | `assertEqual([], [e for e in validate_live_csvs() if "DATA FUTURA" in e])`, `assertEqual(errori, [])`, `assertIn(f"(oggi {adesso.strftime('%d/%m/%Y')}", errori[0])`, conteggi esatti `assertEqual(1, len(...))` di errori su date relative all'ora reale | Al primo aggiornamento (ogni 6 h) con una riga datata oltre la tolleranza di 1 giorno: partita gia' schedulata, refuso di data, righe della stagione successiva. **E' gia' successo il 09/10/2026** (docstring del file). Con certezza al **rollover 01/07/2027** |
| 5 | `SoccerMath/test_season_calendar.py` | `TestSeasonCalendar::test_calendario_reale_nessuna_partita_a_luglio` (62-66) | Tutti i `*.csv` di `DATABASE_DIR`, compresi i Live | `assertFalse((dates.dt.month == 7).any())` e `assertGreater(n, 5000)` sul calendario reale | Quando il robot scrive una partita datata luglio (primo turno della stagione 2027/28, **luglio 2027**) o il rollover lascia una riga di luglio; `n > 5000` cala se i Live vengono svuotati |
| 6 | `SoccerMath/test_alias_quote_live.py` | `TestCoperturaFileLive::test_copertura_completa_anche_sul_file_vivo`; `TestCoperturaCalendariFootballData::test_ogni_nome_dei_calendari_in_cache_su_disco_e_riconosciuto` | `SoccerMath/database/live_odds.json` letto dal disco (oggi `2026-11-01T15:15:10Z`, 63 eventi) + `*_Live.csv` per i nomi canonici | `assertEqual([], dati["non_abbinati"])`, `assertEqual(dati["n_eventi"], dati["n_indicizzati"])`, `assertEqual([], sorted(set(sconosciuti)))` | Al **prossimo refresh quote** (`live_odds.yml`: cron `17 8 * * *` e `47 10 * * *`, quindi ogni giorno entro le 10:47 UTC): basta un nome squadra non presente in `team_aliases.py` per far comparire un evento non abbinato. Con certezza al rollover con le nuove promosse |
| 7 | `SoccerMath/test_alias_quote_live.py` | `TestCoperturaCalendarioCorrente::{test_ogni_partita_e_abbinata_al_calendario_corrente, test_copertura_e_il_100_percento}`; `TestAliasAggiunti::test_i_canonici_degli_alias_sono_nel_calendario_corrente` | `nomi_canonici_stagione_corrente()` legge i 5 `*_Live.csv` dal disco; `eventi_snapshot()` e' lo snapshot committato 08/10 (fisso) | `assertEqual([], non_abbinate)`, `assertEqual(len(self.eventi), abbinate)` (96/96 dichiarato), `assertIn(clean_name(canonico), tutti_canonici)` | Quando una squadra dello snapshot esce dal roster corrente o un nome viene corretto: possibile **gia' alla prossima giornata di novembre 2026**; con certezza al **rollover 01/07/2027** (rose nuove) |
| 8 | `SoccerMath/test_scheda_partita.py` | `TestQuoteEAbbinamento::test_abbina_partite_sullo_snapshot`; `TestSchedaCompleta::{test_blocchi_e_righe_coerenti, test_probabilita_e_forma_sono_quelle_dei_dati, test_precedenti_stagionali_se_gia_giocata}`; `TestFasceEloENonLeakage::test_forma_reale_dal_motore_di_produzione` (chiamate default a righe ~296, 600, 811, 1014) | `sp.carica_risultati_stagione(lega)` **senza `percorso`** → `*_Live.csv` reali dal disco, abbinati allo snapshot quote pinnato `snap_test.snapshot_reale()` del 2026-10-11 e `ADESSO` fisso 16/10. (Le classi `TestClassificaRiconataAMano`, `TestLeHavreEAuxerreSulloSnapshotFissato` usano invece la fixture congelata) | `assertEqual(abb["n_non_abbinate"], 0)`, `assertGreater(p["kickoff_utc"], ADESSO)` (partite future), `assertEqual(precedenti[0]["casa"], riga["casa"])` sui "Precedenti in stagione" di Bologna-Inter, `assertIn(precedenti[0]["risultato"], sp.testo_scheda(scheda))` | Quando una squadra dello snapshot non e' piu' nel Live corrente, o quando il **ritorno Bologna-Inter** entra nel CSV (girone di ritorno, primavera 2027) cambiando l'elenco dei precedenti. Con certezza al **rollover 01/07/2027** |
| 9 | `audit/test_live_odds_match.py` | `TestAbbinamento::{test_partite_e_abbinamenti_per_lega, test_totali, test_copertura_completa_col_resolver_di_produzione, test_prossima_giornata_dentro_la_finestra_di_produzione}` (99-171) | `live_odds_match.build_payload()`: snapshot probe 08/10 (fisso) **ma** `canonical_names(prefix, ["Live"])` legge i `*_Live.csv` reali da `SoccerMath/database`; `generato_il` usa `datetime.now()` reale | `ATTESO` fisso `{(10,10,10),(10,10,10),(10,8,10),(9,7,9),(9,8,9)}` → `assertEqual(v["n_prossima_giornata"], n)`, `assertEqual(t["n_prossima_giornata"], 48)`, `assertEqual(t["n_abbinate"], 43)`, `assertEqual(v["n_prossima_giornata"], v["n_abbinate_resolver"])` | Appena un nome canonico del Live cambia o entra una squadra nuova (prossima giornata di novembre 2026; con certezza promozioni al **rollover 01/07/2027**) gli abbinamenti non sono piu' 48/48 |
| 10 | `audit/test_ng_regression.py` | `TestNameMapping::test_current_season_teams_covered`; `TestNoExtremeNGRegression::test_all_leagues_no_extreme_ng` | `*_Live.csv` + archivi xG reali da `SoccerMath/database`; `_engine(league)` costruisce il motore sui dati correnti | `assertEqual(missing, set())` (copertura nomi della stagione corrente) e `assertLess(worst[2], 0.95)` su **tutte** le coppie di squadre reali di ogni lega | Ogni `update_xg` (cron `0 6 * * 2,5`) e ogni `update_database` (ogni 6 h) cambia le λ: un nome non coperto o λ estreme fanno saltare le due asserzioni. Con certezza al rollover |
| 11 | `SoccerMath/test_rollover_chain_2027.py` | `TestRolloverChain2027` (riga 74) | `shutil.copytree(config.DATABASE_DIR, cls.db)` (riga 79): **copia integrale** del database reale, compresi i 5 `*_Live.csv` | `assertEqual(len(live), 0, "il Live deve ripartire vuoto")` (117), `assertGreater(len(arch), 30)` (118), `assertEqual(int(key.duplicated().sum()), 0)` (120), `assertTrue((seasons == 2026).all())` (124), `assertEqual(before, after)` (129, idempotenza byte-identica), `assertEqual(res["season_not_started"], 2027)` (145) | Simula il rollover a `JULY_2027` sulla copia: se un `update_database` (ogni 6 h) inserisce una riga con data fuori dal 2026 o una coppia duplicata, le asserzioni su `seasons == 2026`, `> 30` righe d'archivio e `duplicated() == 0` cambiano; con certezza al **rollover reale 01/07/2027** |

### 4b. Ora vera non fermata con asserzioni su partite future / giornate

| # | File | Test | Dato che legge | Asserzione a rischio | Stima di quando si rompe |
|---|---|---|---|---|---|
| 12 | `SoccerMath/test_apptest_scheda_pronostici.py` e i **3** file che ne ereditano `_BaseQuoteFinte`: `test_apptest_calendario_leghe.py`, `test_apptest_selezione_tabelle.py`, `test_apptest_totals_mercato.py` | `TestSchedaPronostici::{test_02_pareggi_elenca_le_X_del_periodo, test_03_il_click_calcola_e_lascia_la_tabella_in_vista, test_08_il_periodo_e_un_calcolo_nuovo_non_una_tabella_mista}` (655-699), `TestParitaScrittureColPulsanteVecchio::test_01_stesse_righe_stesse_chiamate`; piu' `TestCalendarioDellaScheda`, `TestTabelleERegistro`, `TestSpuntaNonRimane`, `TestAppTotals` | `cls.ADESSO = datetime.now(timezone.utc)` **non congelato** (docstring: «Le date sono RELATIVE all'orologio reale perche' le quote finte non invecchino»). `FixtureQuoteFinte.pianifica()` piazza 4 partite a +8/+12/+16/+20 h e 1 a `lunedi_gioco(adesso)+96 h`; il guard `if lunedi_gioco(ADESSO) - ADESSO < 26h: ADESSO += 3 giorni` dipende dal **giorno della settimana reale**. Inoltre `_link_del_database()` linka i CSV live reali | `assertEqual(4, len(attese))`, `assertEqual(3, len(in_periodo))` («una gioca dopo lunedi': e' fuori periodo»), `assertIn("3 partite in tabella.", testo)`, `assertIn("Altre 1 nei prossimi giorni.", testo)`, `assertEqual(["Roma - Lecce", ...], list(df["Partita"]))` — conteggi di **partite future** dentro/fuori la giornata | Il confine «in periodo / oltre lunedi'» e' calcolato da `lunedi_gioco()` sull'ora reale: il rischio e' **a ogni cambio di settimana**, in particolare quando il cron della suite (13:37 UTC) cade a ridosso del lunedi' di gioco e scatta lo shift di +3 giorni, o quando cambia la regola del lunedi' di gioco a cavallo del rollover. Oggi (lunedi' 02/11/2026) la suite passa; non e' garantito negli altri giorni della settimana |
| 13 | `SoccerMath/test_apptest_top_mix.py` | `TestAppTestCalcolaTopMix::{test_a_click_top_mix, test_b_archivio_modello_storico_in_riquadro}` (righe 117, 386-405) | Due letture dell'**ora reale non fermata**: `ora = datetime.now(timezone.utc)` in `setUpClass` (kickoff `ora+20h`, `salvato_il ora-1g`, riga storica `ora-30g`) e `_adesso = _dt.now(_tz.utc)` dentro il test. I CSV reali sono linkati nel tmp (riga ~110) | `assertEqual(len(_attese), len(gambe_sel[0].options))` sulle **partite future** selezionabili, con `periodo_val` deciso dal guard `if periodo_val == "giornata" and _lg.lunedi_gioco(_adesso) <= _adesso + timedelta(hours=20): ...`; piu' le asserzioni su `sotto_soglia_ora` e sul modello storico | Le due letture di `now` (setup e test) e il confine del lunedi' di gioco non sono sincronizzati: rischio **a ogni lunedi'/cambio di settimana**, e se la suite attraversa la mezzanotte UTC fra setup e test. Con certezza al cambio di stagione (rollover 01/07/2027) |

### 4c. Letture live ma **auto-coerenti** (censite, non segnalate come bombe a orologeria)

Questi test leggono file live dal disco, ma ricalcolano il valore atteso dallo
stesso file, quindi un semplice avanzamento di giornata non li rompe. Li si
elenca per completezza del censimento, con la condizione che li farebbe cadere:

- `SoccerMath/test_scheda_partita.py::TestClassificaRiconataAMano::{test_una_riga_per_squadra_e_nessun_doppione, test_punti_giocate_gol_identici_al_conteggio_a_mano, test_somma_dei_PUNTI_delle_partite_del_csv, test_ordinamento_e_posizioni}` e `TestGiornateEDistanze::test_distanze_sulla_classifica_vera`: `assertEqual(r["punti"], atteso["punti"])`/`giocate`/`pos` con `atteso = classifica_contata_a_mano(carica_risultati_stagione(CAMP))`, **stesso CSV**. Cadono se il Live contiene una riga duplicata, una data futura o un pareggio che il tie-break non ordina allo stesso modo: possibile a ogni `update_database` (6 h), certo al rollover.
- `SoccerMath/test_season_calendar.py::TestPreSeasonTolerance::test_default_oggi`: usa la data reale ma asserisce su stagioni 2020 e 2099, «deterministico per stagioni lontane» (docstring). Stabile.
- `SoccerMath/test_replay_legacy_no_leakage.py::TestFinestraComplementare::test_nessuna_partita_in_entrambe_le_finestre`: `datetime.now(UTC).date()` come fine finestra, ma le fixture hanno date fisse 18/09/2026 e l'orologio puo' solo avanzare. Stabile.
- `SoccerMath/test_stato_quote_live.py`, `SoccerMath/test_quote_solo_pre_partita.py`: orologio **fermato** (`2026-10-09 20:00Z`) e file temporanei → non dipendono dal live.
- `SoccerMath/test_apptest_calendario_leghe.py::TestTabelleERegistro::test_01_nessun_none_in_nessuna_scheda`: orologio fissato a `2026-10-16 12:00Z` dalla PR #85 → protetto.
- `SoccerMath/test_apptest_topmix_presentazione.py::TestPresentazioneTopMix`: NON eredita `_BaseQuoteFinte` e usa `cls.adesso = datetime(2026, 10, 16, 16, 0, tzinfo=timezone.utc)` con `_DtCongelata` che congela `datetime.now` in app e Registro (righe 373, 463-471) → orologio fermato, protetto.
- `SoccerMath/test_apptest_scheda_grafica.py`, `SoccerMath/test_apptest_scheda_partita.py::TestSelettoreGiornata` (`assertIn("Giornata 8")`, `assertEqual(giornata, 8)`, `0`): **protetti da questo commit**, perche' `_BaseScheda` ora usa la copia congelata della giornata 7.
- `SoccerMath/test_scheda_partita.py::TestLeHavreEAuxerreSulloSnapshotFissato`, `audit/test_live_odds_match.py::TestInsiemeCanonico`: usano `snap_test.blob_del_commit(...)` / snapshot committati → pinnati, non volatili.

**Nessuna correzione e' stata applicata a nessuno dei test delle tabelle 4a/4b/4c.**

---

## 5. Suite completa con `timeout 900`

Popolazione: `git ls-files | grep -E '(^|/)test_[^/]*\.py$' | grep -vx 'SoccerMath/test_theme_toggle.py'`
= **127 file**, `2571 tests collected`. La CI (`.github/workflows/test_suite.yml`)
li esegue in un solo processo con `timeout-minutes: 50`; in locale, per rispettare
`timeout 900`, ho usato 4 worker xdist con `--dist loadfile` (ogni file resta su un
solo worker, come richiesto dallo stato globale condiviso `@st.cache_data`).

```
$ STREAMLIT_BROWSER_GATHER_USAGE_STATS=false timeout 900 /tmp/smvenv/bin/python -m pytest \
    -q -rfE --tb=short -p no:cacheprovider -n 4 --dist loadfile $(cat /tmp/file_pytest.txt)
PYTEST_EXIT=0
=============================== warnings summary ===============================
audit/test_elo_w025_confirmation.py::TestPatchGriglia::test_boot_stats_delta_vs_060_con_griglia_ridotta
  /home/user/SoccerMath2.0/audit/grid_search_ensemble_weight.py:224: RuntimeWarning: invalid value encountered in divide
    rr = np.where(staked > 0, prof / staked, np.nan)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
2563 passed, 8 skipped, 1 warning, 7225 subtests passed in 326.92s (0:05:26)
```

`SoccerMath/test_theme_toggle.py` come script (la CI lo esegue separatamente,
perche' non e' un test pytest), sempre con `timeout 900`:

```
$ cd SoccerMath && STREAMLIT_BROWSER_GATHER_USAGE_STATS=false timeout 900 /tmp/smvenv/bin/python test_theme_toggle.py
THEME_EXIT=0
✅ Run 1 OK - toggle ON (segue tema sistema), nessuna eccezione
✅ Run 2 OK - toggle OFF, CSS light forzato presente (2 blocchi <style>)
✅ Run 3 OK - ritorno a ON, CSS forzato rimosso, nessuna eccezione
✅ Run 4 OK - rerun generico senza crash

🎉 TUTTI I TEST PASSATI: nessun crash in nessuno stato del toggle.
```

---

## 6. Nessuna scrittura nel Registro / nel database

Hash `sha256` di **tutti** i 38 file regolari in `SoccerMath/database/`
(compresi `live_odds.json`, `season_rosters.json`, gli archivi xG) presi prima
della suite e ricontrollati dopo:

```
$ find SoccerMath/database -maxdepth 1 -type f -print0 | sort -z | xargs -0 sha256sum > /tmp/registro_before.sha256
  ... (test singolo, test scheda grafica, suite completa, theme toggle, impronte) ...
$ find SoccerMath/database -maxdepth 1 -type f -print0 | sort -z | xargs -0 sha256sum > /tmp/registro_after.sha256
$ diff -u /tmp/registro_before.sha256 /tmp/registro_after.sha256 && echo "IDENTICI: nessun file di database/Registro riscritto"
IDENTICI: nessun file di database/Registro riscritto
```

`git status --porcelain` dopo la correzione e prima di aggiungere il referto:

```
 M SoccerMath/test_apptest_scheda_partita.py
```

Nessun file non tracciato, nessun `predictions.json` creato. I test usano
Registro in memoria / cartelle temporanee.

---

## 7. Commit, PR e controllo CI (una sola volta)

```
$ git commit -F /tmp/sm_commit_msg.txt            # heredoc <<'EOF'
[arena/4a6ee9b6-soccermath2-0 c9fd8e0] Test scheda: SerieA_Live.csv congelato (giornata 7) nella fixture _BaseScheda
 1 file changed, 37 insertions(+), 1 deletion(-)
$ git push origin arena/4a6ee9b6-soccermath2-0
 * [new branch]      arena/4a6ee9b6-soccermath2-0 -> arena/4a6ee9b6-soccermath2-0
$ gh pr create --base main --head arena/4a6ee9b6-soccermath2-0 \
    --title "Test scheda: fixture SerieA_Live.csv congelata (giornata 7)" \
    --body-file /tmp/sm_pr_body.md               # heredoc <<'EOF'
https://github.com/iFelice/SoccerMath2.0/pull/89
```

**PR**: https://github.com/iFelice/SoccerMath2.0/pull/89

Controllo CI **unico**, eseguito una sola volta con `gh run list` subito dopo
l'apertura della PR (`/tmp/gh_run_list.log`, exit 0):

```
$ gh run list --limit 10
queued		Test scheda: fixture SerieA_Live.csv congelata (giornata 7)	Replay Top Mix legacy (walk-forward, no-leakage)	arena/4a6ee9b6-soccermath2-0	pull_request	41493554244	3s	0m
queued		Test scheda: fixture SerieA_Live.csv congelata (giornata 7)	Audit Top Mix (sola lettura)	arena/4a6ee9b6-soccermath2-0	pull_request	41493554173	3s	0m
queued		Test scheda: fixture SerieA_Live.csv congelata (giornata 7)	Suite test completa	arena/4a6ee9b6-soccermath2-0	pull_request	41493554095	3s	0m
completed	success	Aggiorna Database	Aggiorna Database	main	schedule	41457369997	34s	3h
completed	success	Istantanea giornaliera del Registro (fase E)	Istantanea giornaliera del Registro (fase E)	main	schedule	41443495721	45s	5h
completed	success	Aggiorna Database	Aggiorna Database	main	schedule	41380250508	37s	14h
completed	success	Aggiorna Database	Aggiorna Database	main	schedule	41351834037	35s	20h
completed	success	Replay Top Mix legacy (walk-forward, no-leakage)	Replay Top Mix legacy (walk-forward, no-leakage)	main	schedule	41340132922	12m36s	22h
completed	failure	Suite test completa	Suite test completa	main	schedule	41337076925	36m3s	23h
completed	success	Quote live (The Odds API)	Quote live (The Odds API)	main	schedule	41328769839	16s	1d
```

Lettura: i tre workflow della PR (`Suite test completa`, `Audit Top Mix`,
`Replay Top Mix legacy`) risultano **accodati** al momento dell'unico controllo;
non e' stato fatto nessun secondo controllo. Il run schedulato di
`Suite test completa` su `main` di 23 h prima risulta `failure` (36m3s): e' il
rosso da domenica dovuto al test `test_03` descritto al punto 1. L'esito locale
della suite (punto 5) e' verde.
