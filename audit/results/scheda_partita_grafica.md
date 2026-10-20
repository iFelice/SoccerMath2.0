# Referto — Scheda partita grafica (serie di quattro lavori)

- **Pull request:** https://github.com/iFelice/SoccerMath2.0/pull/81 (aperta, verso `main`, **non mergiata**)
- **Branch:** `arena/bac8798b-soccermath2-0`
- **Data del referto:** 2026-10-20 19:57 CEST (Europe/Rome)
- **Ambiente di verifica:** Python 3.11.2 (venv dedicato), Streamlit 1.66.0, test con `python -m unittest`, fuso `TZ=Europe/Rome`; nessuna rete nei test (fixture con snapshot pinnato e rete finta).

## Diff rispetto a `main`

```
 SoccerMath/app.py                         |  68 ++-
 SoccerMath/scheda_grafica.py              | 661 ++++++++++++++++++++++++++++++
 SoccerMath/scheda_partita.py              |  58 ++-
 SoccerMath/test_apptest_scheda_grafica.py | 209 ++++++++++
 SoccerMath/test_apptest_scheda_partita.py |  33 +-
 SoccerMath/test_scheda_grafica.py         | 301 ++++++++++++++
 SoccerMath/test_scheda_partita.py         |  60 +++
 7 files changed, 1359 insertions(+), 31 deletions(-)
```

Commit della PR, dal più vecchio al più recente:

| Commit | Oggetto |
|---|---|
| `18752279c04607a8003d03ab4ef716ff032245ce` | Scheda partita: pos_prec, posizione alla giornata precedente |
| `9e70973c709cdaf7ae27c529b9b779b978e6f878` | Scheda grafica: sezioni Probabilità e Classifica in HTML puro |
| `cc1366b33640227211f5fdacfbf1d1dfe9ba500b` | Scheda grafica: Forma, Gol, Precedenti e scheda HTML in app |
| `612e9dec544d2068be49433335d0bb7d016f0d5b` | Scheda grafica: tema chiaro con interruttore spento, giornata solo se nota |

## Che cosa contiene la serie

1. **Primo lavoro** — `pos_prec` in `SoccerMath/scheda_partita.py`: posizione alla giornata precedente, con lo stesso conteggio di `classifica()` sui risultati archiviati escluse le partite dell'ultima giornata giocata (massimo della colonna giornata); `None` se non esiste una giornata precedente.
2. **Secondo lavoro** — `SoccerMath/scheda_grafica.py` (nuovo): funzioni pure, scheda → stringhe HTML, niente Streamlit; palette chiara/scura da parametro `tema`; ogni nome/testo dai dati passa da `html.escape`. Sezioni Probabilità e Classifica.
3. **Terzo lavoro** — sezioni Forma, Gol, Precedenti (nota sotto soglia costruita da `market_odds.SOGLIA_TOPMIX_MERCATO`, con simbolo `%`) e uso in app: `_contenuto_scheda_partita` disegna intestazione e cinque sezioni con `st.markdown(..., unsafe_allow_html=True)`, tema da `st.context.theme.type` (light/dark, default dark). `blocchi_scheda`/`testo_scheda` non toccati.
4. **Quarto lavoro** (questo referto) — le due correzioni qui sotto, poi solo verifiche.

## Quarto lavoro: le due correzioni

### 1. Tema chiaro con l'interruttore «Segui tema sistema» spento

`app._tema_scheda_grafica` restituisce ora `light` anche quando `follow_system_toggle` in `st.session_state` è spento: in quel caso la pagina è già forzata in chiaro con `CSS_TEMA_CHIARO_FORZATO`, mentre `st.context` può dire ancora dark (o non essere disponibile). L'interruttore spento vince sul context; invariati il comportamento con interruttore acceso (light/dark dal context) e il fallback dark.

Test: `test_03_interruttore_spento_palette_chiara` in `test_apptest_scheda_grafica.py` spegne l'interruttore per chiave e verifica che la scheda aperta (Bologna–Inter) usi la palette chiara e non quella scura, pur in assenza di un context "light".

### 2. Giornata nella didascalia solo se nota dalla richiesta

`app._contenuto_scheda_partita` mostra «Giornata N» solo se la giornata arriva dalla richiesta (`giornata`/`matchday`, cioè dal calendario). Rimossi la stima `giornate giocate + 1` e la scritta `n/d`: se la giornata non è nota, la didascalia è solo `{data e ora} · {campionato}`.

Test: `test_04_scheda_da_pronostici_senza_giornata` in `test_apptest_scheda_grafica.py` apre una scheda la cui richiesta nasce dalle quote (nomi grezzi della fonte «Bologna»/«Inter Milan» e orario, nessun matchday, come da Pronostici) e verifica: cinque sezioni presenti, didascalia con data, ora e campionato, senza «Giornata» e senza «n/d».

Esiti dei due test nuovi (eseguiti anche singolarmente):

```
test_03_interruttore_spento_palette_chiara ... ok
test_04_scheda_da_pronostici_senza_giornata ... ok  (101.591s, singolarmente)
```

## Impronte del selettore (Python 3.11.2)

`impronta_attuale()` e `impronta_ou_attuale()` di `SoccerMath/test_versione_selettore.py`, calcolate su un worktree separato di `main` (`7720249d806fb705acd23b5d71f77e506d59c018`) e sul branch della PR (`612e9dec544d2068be49433335d0bb7d016f0d5b`), stesso interprete:

| Impronta | `main` | branch | Esito |
|---|---|---|---|
| `impronta_attuale` | `01aaa65657c38e0994986a5f75efb0b4976aa30338057faf3efd566203fd0cad` | `01aaa65657c38e0994986a5f75efb0b4976aa30338057faf3efd566203fd0cad` | identica |
| `impronta_ou_attuale` | `fbb0cb99c42e589c3296a8bc4185c7f5b284bc3d1a67b7e621dabc7517431d8c` | `fbb0cb99c42e589c3296a8bc4185c7f5b284bc3d1a67b7e621dabc7517431d8c` | identica |

Le funzioni cambiate nei quattro lavori non sono tra quelle coperte dalle impronte, e il confronto lo conferma: il selettore non è stato toccato.

## Suite completa (a lotti, timeout 900 s per lotto)

Copertura: tutti i 73 file `SoccerMath/test_*.py`. `test_theme_toggle.py` è uno script e viene eseguito come tale; gli altri 72 moduli sono coperti con `python -m unittest`. Totali: **1556 test unittest** (1464 unitari/integrazione + 92 AppTest) più lo script del tema.

### Lotti unitari e di integrazione (da `SoccerMath/`)

| Lotto | Moduli | Test | Esito |
|---|---|---|---|
| 1 | `test_alias_quote_live`, `test_analisi_rapida_due_motori`, `test_basic`, `test_calendario_cache_errori`, `test_confronto_modelli`, `test_display_names`, `test_doppioni_versioni` | 135 | OK (13.337s) |
| 2 | `test_elo_ensemble_1x2`, `test_elo_probs_from_ratings`, `test_elo_promoted_seed`, `test_esiti_ou_registro`, `test_fallback_nomi`, `test_freschezza_quote` | 116 | OK (3.840s) |
| 3 | `test_legacy_elo_engine`, `test_lista_giocate_v1`, `test_market_prior`, `test_match_stats_pipeline`, `test_model_variant_registry` | 92 | **FAILED (failures=1, skipped=1)** (34.925s) — vedi nota A |
| 4 | `test_multiple_pronostico_partita`, `test_ombra_due_famiglie`, `test_pareggi_soglia`, `test_presentazione_topmix`, `test_problemi_produzione` | 110 | OK (102.222s) |
| 5 | `test_pronostico_partite`, `test_pt19_totali_invariance`, `test_quote_live`, `test_quote_solo_pre_partita`, `test_registro_due_tabelle` | 76 | OK (1.879s) |
| 6 | `test_registry_backend_status`, `test_registry_composizione`, `test_registry_coverage`, `test_registry_grading`, `test_registry_migrate`, `test_registry_modelli_check`, `test_registry_pulizia`, `test_registry_snapshot`, `test_registry_store`, `test_registry_tracking` | 230 | OK (29.162s) |
| 7 | `test_replay_legacy_no_leakage`, `test_rifiniture_registro`, `test_righe_non_ricostruite`, `test_rollover`, `test_rollover_chain_2027`, `test_roster_fallback_replay` | 132 | OK (43.059s) |
| 8 | `test_scheda_grafica`, `test_scheda_partita`, `test_season_calendar`, `test_season_rosters`, `test_standardizza_mercato`, `test_stato_quote_live`, `test_tabelle_sigle_percentuali` | 217 | OK (24.604s) |
| 9 | `test_topmix_dual_tables`, `test_topmix_mercato`, `test_topmix_ombra_totali`, `test_topmix_selector_parity`, `test_topmix_shadow_gate`, `test_totals_correzioni`, `test_totals_mercato`, `test_update_live_odds`, `test_versione_selettore`, `test_xg_pipeline` | 356 | OK (17.921s) |

### Lotti AppTest (uno per file)

| Lotto | Modulo | Test | Esito |
|---|---|---|---|
| A1 | `test_apptest_calendario_leghe` | 3 | **FAILED (failures=1)** (255.479s) — vedi nota B |
| A2 | `test_apptest_multipla` | 4 | OK (1.050s) |
| A3 | `test_apptest_multiple_riquadri` | 7 | **FAILED (failures=2, skipped=1)** (114.049s) — vedi nota B |
| A4 | `test_apptest_navigazione` | 17 | OK (182.202s) |
| A5 | `test_apptest_scheda_grafica` | 4 | OK (154.238s) |
| A6 | `test_apptest_scheda_partita` | 12 | OK (skipped=1) (184.130s) |
| A7 | `test_apptest_scheda_pronostici` | 15 | **FAILED (failures=1)** (198.835s) — vedi nota B |
| A8 | `test_apptest_selezione_tabelle` | 5 | OK (95.463s) |
| A9 | `test_apptest_top_mix` | 2 | OK (89.366s) |
| A10 | `test_apptest_topmix_presentazione` | 12 | OK (113.974s) |
| A11 | `test_apptest_totals_mercato` | 11 | OK (121.312s) |

### Script `test_theme_toggle.py` (eseguito come script)

```
✅ Run 1 OK - toggle ON (segue tema sistema), nessuna eccezione
✅ Run 2 OK - toggle OFF, CSS light forzato presente (2 blocchi <style>)
✅ Run 3 OK - ritorno a ON, CSS forzato rimosso, nessuna eccezione
✅ Run 4 OK - rerun generico senza crash

🎉 TUTTI I TEST PASSATI: nessun crash in nessuno stato del toggle.
```
Exit code 0.

### Nota A — `test_legacy_elo_engine` (lotto 3): fallimento identico su `main`

```
FAIL: test_git_conferma_il_commit_che_lo_ha_sostituito
AssertionError: '980e04851b91345e697e62fe7f50b425a3d6d2b5 2026-09-18T21:39:23+00:00\n' is not None
```

Il test si aspetta che in un clone superficiale (`is-shallow-repository` = true) la cronologia del commit dichiarato non sia presente. In questo clone la cronologia è stata approfondita in precedenza (`git fetch --deepen=400 origin main`, necessario per gli snapshot pinnati), quindi l'oggetto è presente pur restando il clone marcato superficiale. **Lo stesso test, eseguito da solo sul worktree di `main`, fallisce con lo stesso identico messaggio**: è un artefatto dell'ambiente di verifica, non una regressione del branch (il branch non tocca il motore legacy).

### Nota B — Tre AppTest con attese sui vecchi titoli dei blocchi di testo

Tre file AppTest **non** aggiornati nel terzo lavoro (che ha aggiornato solo `test_apptest_scheda_partita.py`, come da perimetro) controllano ancora i titoli dei vecchi blocchi di testo di `blocchi_scheda`, mentre dal terzo lavoro la scheda disegna le sezioni HTML con titoli «Probabilità» e «Classifica»:

| File | Test | Attesa non più valida |
|---|---|---|
| `test_apptest_calendario_leghe.py` | `test_01_ogni_lega_ha_il_suo_calendario` | «Classifica e obiettivi» (e il pattern `\d+° posto`) |
| `test_apptest_multiple_riquadri.py` | `test_06_selezionare_la_riga_apre_la_scheda_di_quella_partita` (righe 0 e 2) | «Probabilità (dalle quote dei bookmaker)» |
| `test_apptest_scheda_pronostici.py` | `test_05_cliccare_una_riga_apre_la_scheda_di_quella_partita` | «Probabilità (dalle quote dei bookmaker)» |

In tutti i casi la scheda si apre e le cinque sezioni HTML sono presenti e popolate: cade solo l'asserzione sul vecchio titolo testuale. Per istruzione del quarto lavoro («dopo le due correzioni, nessuna altra modifica al codice») questi test **non** sono stati aggiornati qui: resta da decidere se aggiornarne le attese ai titoli HTML in un lavoro successivo. Su `main` gli stessi test passano, perché lì la scheda mostra ancora i blocchi di testo.

## Verifiche finali sullo stato del lavoro

- `git status --porcelain` dopo le correzioni e prima di questo referto: **vuoto** (nessun file modificato o non tracciato). Worktree temporaneo di `main` rimosso.
- Run CI sul branch della PR (`gh run list --branch arena/bac8798b-soccermath2-0`), ultimi run sull'head `612e9dec544d2068be49433335d0bb7d016f0d5b`:
  - `39465391263` Audit Top Mix (sola lettura) — completed/success
  - `39465391269` Replay Top Mix legacy (walk-forward, no-leakage) — completed/success
  - `39465391264` Suite test completa — completed/**failure**
  
  Il dettaglio del job CI non è scaricabile da questo ambiente (l'host dei log non è tra quelli raggiungibili); localmente la suite mostra i fallimenti documentati nelle note A e B, della stessa natura (attese/ambiente), e nessun altro.
- Nessun merge è stato fatto: la PR #81 resta aperta verso `main` con i quattro commit elencati sopra.
