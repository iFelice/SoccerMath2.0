# Referto — PR #72: il periodo sopra le schede, celle di testo, meno parole nei Pronostici

Correzioni di SOLA PRESENTAZIONE in `SoccerMath/app.py`: nessun numero, nessuna regola
di selezione del Top Mix, nessuna riga di Registro, nessun workflow toccati.

- Contenuto verificato: head della PR #72 (`3f73dc0`, che poggia su `4805c2d`), branch
  `arena/c67fea69-soccermath2-0`.
- Verifica eseguita il 2026-10-14 dal branch di sessione `arena/7622b1d9-soccermath2-0`
  (che contiene lo stesso codice più questo referto).
- Ambiente locale: Python 3.11.2, streamlit 1.66.0, pandas 3.0.6, numpy 2.4.6,
  scipy 1.17.1, pytest 9.1.1 (stesse dipendenze dei workflow:
  `SoccerMath/requirements.txt` + `requirements-audit.txt` + `pytest`).

---

## 1. Interruttore del periodo — un solo widget, sopra le schede

| Voce | Prima | Adesso |
|---|---|---|
| Dove sta il widget | `st.toggle` in testa alla scheda «🎯 Multiple» | `st.toggle` **prima di `st.tabs`**, una volta sola per pagina |
| Chi lo legge | solo Multiple (Pronostici e Pareggi si limitavano a citarlo) | `periodo_selezionato()`, cioè **Pronostici, Pareggi e Multiple** |
| Chiave / etichetta | `lg_periodo_prossimi` / «Mostra anche i prossimi giorni» | identiche (nessun cambio di stato per chi era già acceso) |

Prove (AppTest, sul vero `app.py`):

- `test_apptest_scheda_pronostici.py::test_12_l_interruttore_e_sopra_le_schede_e_vale_per_tre_schede`:
  un solo toggle con la chiave del periodo in tutta la pagina, **zero** toggle dentro le
  schede Pronostici, Pareggi, Multiple e Registro; acceso, la scheda Pareggi guadagna una
  riga, la tabella di Multiple si allunga e i Pronostici si ritirano chiedendo un clic
  nuovo (altro calcolo, nessuna tabella mista); spento, tutto torna com'era.
- `test_apptest_navigazione.py` e `test_apptest_topmix_presentazione.py::test_06`
  controllano la stessa posizione e la stessa chiave.
- Nella pagina resa gli interruttori sono tre e il primo è quello del periodo:
  `('Mostra anche i prossimi giorni', 'lg_periodo_prossimi')`, poi
  `('🔧 Strumenti avanzati', 'strumenti_avanzati')` e `('🌓 Segui tema sistema', ...)`.

La caption dei Pronostici (dopo il clic) è fatta di due fatti e nient'altro:
`N partite in tabella.` più, quando l'interruttore è **spento** e restano partite oltre
il lunedì, `Altre M nei prossimi giorni.` — nessun rimando a un'altra scheda, nessuno
stato di «Modello %» raccontato nella caption (la cella vuota parla da sola).
Riferimento: `caption_scelte_secondo_le_quote()` e i suoi test in
`test_tabelle_sigle_percentuali.py` (`test_caption_solo_le_partite`,
`test_caption_nei_prossimi_giorni`, `test_caption_non_rimanda_ad_altre_schede`,
`test_caption_non_parla_del_modello`).

## 2. Celle vuote: nessun «NaN», nessun «None» in tabella

- «Modello %» è **testo** con la virgola italiana (`83,3`) e **stringa vuota** dove il
  modello non ha una lettura: `percentuale_in_colonna()`.
- «Quota» è testo con la virgola italiana (`1,45`, `3,38`) e stringa vuota dove manca:
  `quota_in_colonna()` (stessa formattazione di `lista_giocate.quota_italiana`).
- Sola «Quote %» resta **numerica** (`NumberColumn`, una cifra decimale): è quella per
  cui la tabella è ordinata, e l'ordinamento iniziale è `Quote %` decrescente, stabile.
- Anche la tabella del Registro (vista «Com'è andata», punto 5b) usa testo per
  «Modello %» e `cella_di_testo()` per Risultato ed Esito: nessuna cella rende «None».

Prove:

- `test_apptest_scheda_pronostici.py::test_13_nel_testo_reso_zero_nan_zero_none`:
  nel testo RESO delle schede Pronostici e Pareggi, con almeno una riga senza modello,
  **zero** occorrenze di `NaN`/`nan`/`None`/`nat` (e di «n/d» dentro le celle).
- `test_tabelle_sigle_percentuali.py`: «Modello %» vuota per ogni stato non pronto
  (`None`, `in_calcolo`, `non_disponibile`), testo con la virgola quando il giro è
  pronto, «Quota» a due decimali e vuota quando manca; «Quote %» numerica e ordinata.
- `test_apptest_topmix_presentazione.py::test_09` ripete il controllo sulla riga di
  Registro senza lettura del modello.

Controllo indipendente eseguito qui (script di sola lettura sull'AppTest della stessa
fixture, modello dichiarato non disponibile): `0` occorrenze in Pronostici e `0` in
Pareggi — le colonne «Modello %» delle due tabelle rendono due spazi, non un «NaN».

## 3. Meno testo nei Pronostici — le frasi tolte

Via, in questa tornata (le stesse non compaiono più in nessuna scheda):

1. sotto il pulsante «📝 Calcola i pronostici della giornata»:
   «Calcola le scelte della giornata sulle quote del file, le registra nel Registro e
   mostra la tabella qui sotto. Nessun servizio esterno viene chiamato.»
2. l'avviso sulle quote vecchie, che era fatto di due righe e portava una data ISO:
   «⚠️ Le quote sono ferme a 3.0 giorni fa (aggiornate il 2026-10-13T16:04:13Z):
   l'aggiornamento quotidiano non e' riuscito, quindi le probabilita' qui sotto sono
   quelle di allora.» — sostituita da UNA riga in italiano, per esempio
   «⚠️ Quote di martedì 13/10 alle 18:04: l'aggiornamento di oggi non è ancora arrivato.»
3. la caption di freschezza nel suo caso «vecchie quote»
   (`lista_giocate.aggiornamento_quote_parole`): «Attenzione: quote di ieri, non ancora
   aggiornate oggi.» / «Attenzione: quote di martedì 13/10, non aggiornate oggi.» —
   la stessa cosa detta due volte, adesso si dice una volta sola.
4. la vecchia caption dei Pronostici:
   «N partite in tabella · Modello %: in calcolo.» (o «· Modello %: non disponibile.»)
   e «Altre M dopo lunedì: «Mostra anche i prossimi giorni» si accende nella scheda
   🎯 Multiple.» — al loro posto «N partite in tabella.» e «Altre M nei prossimi giorni.»
5. «Accendi «Mostra anche i prossimi giorni» nella scheda 🎯 Multiple per vederle.»
   (Pronostici, nessuna partita nel periodo) → «… in alto per vederle.»
6. «Accendi «Mostra anche i prossimi giorni» nella scheda 🎯 Multiple per guardare più
   avanti.» (Pareggi) → «… in alto per guardare più avanti.»
7. «… Le scelte 1X2 dei due modelli interni non sono piu' in tabella …» (caption della
   scheda Multiple) → «… non sono più in tabella …» (accento, non apostrofo).

Non sono frasi ma sono sparite dalla vista anche le configurazioni numeriche di
«Modello %» e «Quota» (`NumberColumn` con `format="%.1f%%"` e `format="%.2f"`), che
nelle celle vuote si portavano dietro il «NaN»: adesso sono `TextColumn` con testo già
formattato. Il widget del periodo non è stato solo riscritto: è stato **rimosso** dalla
scheda Multiple e ricreato sopra le schede (una chiave non può alimentare due widget).

## 4. Testo reso da AppTest (fixture a quote finte, orologio fermo, Registro in memoria)

Interruttore spento, giro del modello dichiarato non disponibile, clic sul pulsante.

### ⚽ Pronostici — prima del clic (prime 3 righe)

```
 1.  Pronostici
 2.  Calcola i pronostici della giornata
 3. Ultima registrazione: domenica 04/10/2026, ore 17:30
```

### ⚽ Pronostici — dopo il clic (12 righe in vista; le prime 5)

```
 1.  Pronostici
 2.  Calcola i pronostici della giornata
 3. Ultima registrazione: mercoledì 14/10/2026, ore 19:30
 4. ** Registrate 3 giocate nuove**
 5. #####  Le scelte più sicure secondo le quote
 6. Le probabilità vengono dalle quote dei bookmaker, che in media sbagliano meno di
    qualunque modello. La scelta (1/X/2) è quella con la probabilità più alta, e compare
    se supera il **55%**; accanto c'è la probabilità che il nostro modello dà allo stesso
    esito («Modello %»; per le doppie chance è la somma delle due probabilità 1X2).
 7. Quote aggiornate oggi alle 19:30
 8. 3 partite in tabella. Altre 1 nei prossimi giorni.        <- la caption
 9. Quando Partita Pronostico Quote % Modello % Quota
10. gio 15/10, 15:30 Roma - Lecce 1 66.0  1,45
11. gio 15/10, 07:30 Genoa - Fiorentina 1 60.0  1,59
12. gio 15/10, 11:30 Napoli - Venezia 2 58.0  1,64
```

Nella riga 8 i due fatti: le partite in tabella e quelle che restano fuori perché
giocano dopo il lunedì (l'interruttore è spento). Nelle righe 10-12 «Modello %» è la
cella vuota fra `66.0` e `1,45`; «Quota» è testo con la virgola.

### 🟰 Pareggi — tutte le righe in vista (prime 5)

```
 1.  Pareggi
 2. Anche il pareggio più probabile esce circa 1 volta su 3.
 3. Quando Partita Pronostico Quote % Modello % Quota
 4. gio 15/10, 03:30 Torino - Como X 28.0  3,38
 5. gio 15/10, 07:30 Genoa - Fiorentina X 25.0  3,78
 6. gio 15/10, 11:30 Napoli - Venezia X 22.0  4,30
 7. gio 15/10, 15:30 Roma - Lecce X 20.0  4,73
```

Controllo sul testo reso: `0` occorrenze di `nan`/`none`/`nat` in entrambe le schede.

## 5. Suite completa (i due passi del workflow «Suite test completa»)

```
pytest -q -rfE --tb=short -p no:cacheprovider --durations=15 <109 file test_*.py tracciati>
python SoccerMath/test_theme_toggle.py
```

Esito: **2291 passed, 2 skipped, 1 warning, 5303 subtests passed in 540.65s (0:09:00)**,
exit 0; `test_theme_toggle.py`: 4 run su 4 senza eccezioni (toggle ON, OFF, ritorno ON,
rerun generico), exit 0.

Ultime 15 righe reali della suite:

```
33.81s setup    SoccerMath/test_apptest_topmix_presentazione.py::TestPresentazioneTopMix::test_01_la_pagina_si_apre_senza_eccezioni
29.15s setup    SoccerMath/test_apptest_navigazione.py::TestSchedeLettura::test_01_le_schede_sono_quattro_e_la_prima_e_pronostici
29.06s setup    SoccerMath/test_apptest_scheda_partita.py::TestSchedaPartitaAppTest::test_01_il_pulsante_scheda_apre_la_partita_giusta
28.16s setup    SoccerMath/test_apptest_navigazione.py::TestScrittureSoloSuClick::test_01_aprire_e_ridisegnare_non_scrive_nulla
25.66s setup    audit/test_bookmaker_source_test.py::TestCopertura::test_b365_avg_max_coprono_tutto
24.78s setup    audit/test_bookmaker_source_test.py::TestValutazioneCompleta::test_campioni
24.06s setup    SoccerMath/test_apptest_scheda_pronostici.py::TestSchedaPronostici::test_01_prima_del_click_la_scheda_non_mostra_numeri
22.73s setup    SoccerMath/test_apptest_top_mix.py::TestAppTestCalcolaTopMix::test_a_click_top_mix
10.09s call     SoccerMath/test_apptest_top_mix.py::TestAppTestCalcolaTopMix::test_a_click_top_mix
8.28s call     SoccerMath/test_apptest_navigazione.py::TestSchedeLettura::test_09_controllo_risultati_parte_da_solo_una_volta
8.18s call     audit/test_ng_regression.py::TestNoExtremeNGRegression::test_all_leagues_no_extreme_ng
7.44s call     SoccerMath/test_apptest_navigazione.py::TestScrittureSoloSuClick::test_05_se_il_modello_non_risponde_il_resto_resta_in_piedi
7.09s call     audit/test_elo_walker_parity.py::TestProvenienzaFixture::test_v3_fixture_rigenerabile_dal_commit_dichiarato
6.75s call     SoccerMath/test_lista_giocate_v1.py::TestStimaBet365::test_parita_numerica_errore_mediano_test_2025_26
2291 passed, 2 skipped, 1 warning, 5303 subtests passed in 540.65s (0:09:00)
```

Nota di trasparenza. Una prima esecuzione in un clone **superficiale** (`git rev-parse
--is-shallow-repository` = `true`) ha chiuso con 2 falliti: `test_legacy_elo_engine.py::
TestProvenienzaVerbatim::test_git_conferma_il_commit_che_lo_ha_sostituito` e
`audit/test_reconstruct_topmix_match.py::TestHistoricalGitRef::test_main_head_at_xg_commit`.
Sono due test della **cronologia git**, non del codice: il primo pretende l'assenza del
commit quando il clone è superficiale ma lo trova comunque (la storia era arrivata con
il fetch del branch), il secondo cerca un commit di `origin/main` prima del 2026-09-05
che in un clone tagliato non esiste. Con la storia completa (`git fetch --unshallow`,
cioè quello che fa la CI con `fetch-depth: 0`) **passano entrambi** — verificato
eseguendoli da soli: `2 passed in 29.78s`. La suite riportata sopra è la seconda
esecuzione, a clone completo.

## 6. CI (branch `arena/c67fea69-soccermath2-0`, head `3f73dc0`)

| Workflow | Run | Esito |
|---|---|---|
| Suite test completa | [38605295157](https://github.com/iFelice/SoccerMath2.0/actions/runs/38605295157) | ✅ success |
| Audit Top Mix (sola lettura) | [38605295020](https://github.com/iFelice/SoccerMath2.0/actions/runs/38605295020) | ✅ success |
| Replay Top Mix legacy (walk-forward, no-leakage) | [38605295253](https://github.com/iFelice/SoccerMath2.0/actions/runs/38605295253) | ✅ success |

Tutti e tre i workflow della PR erano **già conclusi** al controllo (partiti alle
17:16:45-46Z del 2026-10-14). I due run falliti che compaiono nella stessa lista sono
su `main`, schedulati e non collegati a questa PR: «Aggiorna Database» (16:01:48Z) e
«Istantanea giornaliera del Registro (fase E)» (09:28:06Z).

## 7. Replay del Top Mix di mercato (`topmix_mercato_v3`)

`python audit/replay_topmix_mercato.py` (offline, sola lettura, exit 0):

| Voce | n PR #49 | n replay | Δn | hit PR #49 | hit replay | Δhit | coincide |
|---|---|---|---|---|---|---|---|
| scelte_mercato | 1302 | 1302 | +0 | 0.6751 | 0.6751 | +0.0000 | SÌ |
| accordo | 1144 | 1144 | +0 | 0.6818 | 0.6818 | +0.0000 | SÌ |
| senza_accordo | 335 | 335 | +0 | 0.4358 | 0.4358 | +0.0000 | SÌ |

**Esito: PARITÀ** — la presentazione non ha toccato la selezione del Top Mix. L'unica
differenza nel file rigenerato `audit/results/replay_topmix_mercato.md` era la riga di
intestazione (istante, commit, branch di chi l'ha lanciato): il file è stato lasciato
com'è nella PR, perché i numeri non cambiano.

## 8. Test aggiunti/aggiornati dalle due tornate della PR (contenuto verificato)

Nella tornata di queste tre correzioni (`3f73dc0`):

- `SoccerMath/test_apptest_scheda_pronostici.py` — `test_12` (l'interruttore è fuori
  dalle schede e vale per Pronostici, Pareggi e Multiple), `test_13` (zero «NaN» e zero
  «None» nel testo reso), più le prove sulla caption e sulla tabella dopo il clic.
- `SoccerMath/test_tabelle_sigle_percentuali.py` — «Modello %» testo/vuota, «Quota»
  testo, sola «Quote %» numerica, caption fatta dei due soli fatti.
- `SoccerMath/test_apptest_navigazione.py` e `test_apptest_topmix_presentazione.py` —
  allineati alla posizione nuova del widget.

Nel commit precedente della PR (`4805c2d`, le schede «Pronostici» e «Pareggi»):
`test_apptest_scheda_pronostici.py` (nuovo), `test_apptest_top_mix.py`,
`test_topmix_dual_tables.py`, `test_topmix_mercato.py`, `test_registro_due_tabelle.py`,
`test_rifiniture_registro.py`, `test_stato_quote_live.py`, `test_elo_ensemble_1x2.py`,
`test_problemi_produzione.py`, `audit/test_prediction_registry_date_sorting.py`.

## 9. Cosa NON è cambiato

- Numeri, soglie e formule (replay §7 a parità: Δn = +0 su tutti e tre i gruppi).
- Selezione del Top Mix (`app.seleziona_riga_top_mix_mercato`) e registro ombra.
- Registro: nessuna scrittura nuova, nessun campo, nessuna migrazione; cambia solo il
  modo in cui due colonne si mostrano a schermo (§2).
- Workflow: nessuno toccato.
- Restano, fuori dal perimetro di questa PR, alcune stringhe in vista che usano ancora
  l'apostrofo al posto dell'accento (per esempio «non e'» nella caption dei Pronostici
  quando il file delle quote manca, «piu' probabili» nel riquadro chiuso «Dettagli»
  della scheda Multiple, alcune caption della scheda Registro). Sono preesistenti,
  elencate qui per completezza e **non** toccate: in parte sono fissate da test esistenti
  (per esempio `test_apptest_top_mix.py` pretende «Affidabilita' per registrazione»).
