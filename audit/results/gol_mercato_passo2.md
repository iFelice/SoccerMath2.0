# Passo 2 — Registro, tabella «⚽ Gol — mercato»

- **Pull request:** https://github.com/iFelice/SoccerMath2.0/pull/79
- **Branch:** `arena/8c687131-soccermath2-0`
- **Base `main`:** `93e6537b33e3c015efbf4241761e169ca2138ed4`
- **Data del referto:** 2026-10-19 (Europe/Rome)

## Diff stat rispetto a `main`

```text
$ git diff --stat main
 SoccerMath/app.py                         | 140 ++++++++++++++++++---
 SoccerMath/test_apptest_totals_mercato.py | 202 +++++++++++++++++++++++++++++-
 audit/results/gol_mercato_passo2.md       | 136 ++++++++++++++++++++
 3 files changed, 457 insertions(+), 21 deletions(-)
```

Diff stat sui soli file di codice/test prima del referto (`197010f`):

```text
$ git diff --stat main 197010f
 SoccerMath/app.py                         | 140 ++++++++++++++++++---
 SoccerMath/test_apptest_totals_mercato.py | 202 +++++++++++++++++++++++++++++-
 2 files changed, 321 insertions(+), 21 deletions(-)
```

---

## 0. Cosa cambia

1. **Scala 0–100 di `Quote %` e `Insieme %`**:
   - Nella tabella **⚽ Gol — mercato** del Registro, `prob_mercato_prima` e `prob_congiunta` (frazioni `0–1`) passano da `percento_decimale(...)` prima di `percentuale_in_colonna(...)`.
   - Sullo snapshot del 16/10: `Bayern Munich - RB Leipzig` mostra `85,1` (`Quote %`) e `70,4` (`Insieme %`); `Real Madrid - Sevilla` mostra `68,2` (`Quote %`) e `59,0` (`Insieme %`); `Hamburger SV - VfB Stuttgart` (solo O/U) mostra `69,3` e `""`.

2. **Colonne in vista, tabella tecnica nei Dettagli e ordine delle righe**:
   - Colonne in vista (`COLONNE_GOL_MERCATO`): `Quando`, `Partita`, `Pronostico`, `Quote %`, `Insieme %`, `Risultato`, `Esito` (`⏳`, `✅`, `❌`).
   - `Modello %`, `Fonte` e `Linea Pinnacle` (`COLONNE_GOL_MERCATO_TECNICA`: `Partita`, `Pronostico`, `Modello %`, `Fonte`, `Linea Pinnacle`) sono spostate in una tabella tecnica separata (`tabella_gol_mercato_tecnica`) dentro l'expander chiuso **🔎 Dettagli** del Registro, con la didascalia `totals_mercato_v1 · prima registrazione · Modello %: n/d`.
   - Ordinamento (`ordina_righe_gol_mercato`): prima le righe in attesa (`⏳`) per orario di inizio crescente, poi le concluse (`✅`, `❌`) dalla più recente (orario di inizio decrescente).
   - Il calcolo di `data` e `stagione` per le righe del Registro resta identico a `main` (`df_preds['stagione'] = df_preds['data'].apply(calcola_stagione_calcolo)`).

3. **Riepilogo sopra la tabella e filtri della scheda Registro**:
   - Sopra la tabella **⚽ Gol — mercato** compare la riga di riepilogo (`sintesi_gol_mercato`):
     - Con voci concluse: `Gol: finora N giocate concluse, M riuscite (x%). Quote: y%.` (dove `y` è la media delle probabilità di prima registrazione sulle stesse voci concluse).
     - Senza voci concluse: `Gol: nessuna giocata conclusa finora.`
   - I quattro filtri della scheda Registro (`Campionato`, `Esito`, `Origine`, `Stagione`) valgono anche per questa tabella, e il filtro `Origine` espone sempre la voce `Gol (mercato)`.

---

## 1. Impronte del selettore (Python 3.11)

Calcolate con `SoccerMath/test_versione_selettore.py` (`impronta_attuale` e `impronta_ou_attuale`) su `main` (`93e6537`) e sul branch:

```text
Python: 3.11.2
impronta_attuale (main):      1d2787b0f45b0f91a6ba651809b6e9ecdb2ba7dec35972dafdb40814186a4bb5
impronta_attuale (branch):    1d2787b0f45b0f91a6ba651809b6e9ecdb2ba7dec35972dafdb40814186a4bb5
impronta_ou_attuale (main):   fbb0cb99c42e589c3296a8bc4185c7f5b284bc3d1a67b7e621dabc7517431d8c
impronta_ou_attuale (branch): fbb0cb99c42e589c3296a8bc4185c7f5b284bc3d1a67b7e621dabc7517431d8c
```

| Impronta | `main` (`93e6537`) | Branch (`197010f`) | Stato |
|---|---|---|---|
| `impronta_attuale` (`topmix_mercato_v3`) | `1d2787b0f45b0f91a6ba651809b6e9ecdb2ba7dec35972dafdb40814186a4bb5` | `1d2787b0f45b0f91a6ba651809b6e9ecdb2ba7dec35972dafdb40814186a4bb5` | Identica |
| `impronta_ou_attuale` (`totals_mercato_v1`) | `fbb0cb99c42e589c3296a8bc4185c7f5b284bc3d1a67b7e621dabc7517431d8c` | `fbb0cb99c42e589c3296a8bc4185c7f5b284bc3d1a67b7e621dabc7517431d8c` | Identica |

---

## 2. Test di `SoccerMath/test_apptest_totals_mercato.py`

- `test_08_tabella_gol_mercato_registro_scala_percentuale`: verifica colonne in vista (`Quando`, `Partita`, `Pronostico`, `Quote %`, `Insieme %`, `Risultato`, `Esito`), ordine delle 4 righe in attesa dello snapshot del 16/10, valori `85,1` / `70,4` per `Bayern Munich - RB Leipzig` e `68,2` / `59,0` per `Real Madrid - Sevilla`, e presenza di `Modello %`, `Fonte`, `Linea Pinnacle` nella tabella tecnica dentro `Dettagli`.
- `test_09_ordine_tabella_gol_mercato_in_attesa_e_concluse_mescolate`: verifica con 5 righe mescolate (2 in attesa e 3 concluse) che le righe in attesa vengano prima per orario di inizio crescente (`18/10 15:00` → `18/10 20:45`) e le concluse dopo dalla più recente (`16/10 20:45` → `15/10 18:30` → `14/10 20:45`).
- `test_10_riepilogo_gol_mercato_dieci_concluse_otto_riuscite`: verifica la frase senza voci concluse (`Gol: nessuna giocata conclusa finora.`) e con 10 voci O/U concluse di cui 8 riuscite e 2 fallite (`Gol: finora 10 giocate concluse, 8 riuscite (80%). Quote: 72%.`).
- `test_11_filtri_esito_e_origine_su_tabella_gol_mercato`: verifica con AppTest i filtri `Origine` (`Gol (mercato)`, `Top Mix`) ed `Esito` (`Vinte (✅)`, `Perse (❌)`, `Tutti`) direttamente sui selectbox della scheda Registro.

```text
$ timeout 900 python3 -m pytest -q -rfE -rs --tb=line -p no:cacheprovider SoccerMath/test_apptest_totals_mercato.py
....s......                                                              [100%]
=========================== short test summary info ============================
SKIPPED [1] SoccerMath/test_apptest_totals_mercato.py:127: commit b837823 non raggiungibile (clone shallow)
10 passed, 1 skipped in 131.95s (0:02:11)
```

---

## 3. Suite completa a lotti (`timeout 900` per lotto) e `test_theme_toggle.py`

Elenco dei file: `git ls-files | grep -E '(^|/)test_[^/]*\.py$' | grep -vx 'SoccerMath/test_theme_toggle.py'` → **116 file**, divisi in 7 lotti (3 lotti non-AppTest + 4 lotti AppTest), ciascuno eseguito con `timeout 900 python3 -m pytest -q -rfE -rs --tb=line -p no:cacheprovider "${F[@]}"`:

| Lotto | File | Esito |
|---|---|---|
| 01 | 36 | **803 passed, 11 skipped, 31 subtests passed** in 73.13s (0:01:13) |
| 02 | 36 | 7 failed, **736 passed**, 23 skipped, 4823 subtests passed in 184.22s (0:03:04) |
| 03 | 34 | 3 failed, **687 passed**, 5 skipped, 51 subtests passed in 81.22s (0:01:21) |
| 04 | 3 | **7 passed, 7 skipped, 950 subtests passed** in 274.32s (0:04:34) |
| 05 | 3 | **18 passed, 26 skipped, 117 subtests passed** in 120.49s (0:02:00) |
| 06 | 3 | **7 passed, 12 skipped** in 173.17s (0:02:53) |
| 07 | 1 | **10 passed, 1 skipped** in 131.95s (0:02:11) |
| **Totale** | **116** | **2268 passed, 10 failed, 85 skipped, 5972 subtests passed** |

I 10 test falliti (nei lotti 02 e 03) sono tutti preesistenti e dovuti al clone shallow del sandbox (cercano commit storici non presenti nel clone shallow: `audit/test_elo_probs_equivalence.py`, `audit/test_elo_s3_parity.py`, `audit/test_elo_walker_parity.py`, `audit/test_reconstruct_topmix_match.py`). Gli 85 skip sono anch'essi dovuti al clone shallow e alle cache opzionali non presenti nel sandbox.

### `SoccerMath/test_theme_toggle.py` (eseguito come script)

```text
$ timeout 900 python3 SoccerMath/test_theme_toggle.py
✅ Run 1 OK - toggle ON (segue tema sistema), nessuna eccezione
✅ Run 2 OK - toggle OFF, CSS light forzato presente (2 blocchi <style>)
✅ Run 3 OK - ritorno a ON, CSS forzato rimosso, nessuna eccezione
✅ Run 4 OK - rerun generico senza crash

🎉 TUTTI I TEST PASSATI: nessun crash in nessuno stato del toggle.
```

---

## 4. Stato del repository e CI (singola osservazione senza attese)

```text
$ git status --porcelain
(vuoto)
```

Singola chiamata `gh run list` filtrata sul branch della PR:

```text
$ gh run list --branch arena/8c687131-soccermath2-0 --limit 20
completed	success	Registro, tabella Gol - mercato: scala 0-100 per Quote % e Insieme %	Suite test completa	arena/8c687131-soccermath2-0	pull_request	39271473832	25m45s	36m
completed	success	Registro, tabella Gol - mercato: scala 0-100 per Quote % e Insieme %	Audit Top Mix (sola lettura)	arena/8c687131-soccermath2-0	pull_request	39271473529	6m17s	36m
completed	success	Registro, tabella Gol - mercato: scala 0-100 per Quote % e Insieme %	Replay Top Mix legacy (walk-forward, no-leakage)	arena/8c687131-soccermath2-0	pull_request	39271473491	6m56s	36m
completed	success	Registro, tabella Gol - mercato: scala 0-100 per Quote % e Insieme %	Replay Top Mix legacy (walk-forward, no-leakage)	arena/8c687131-soccermath2-0	pull_request	39266775296	10m43s	1h
completed	success	Registro, tabella Gol - mercato: scala 0-100 per Quote % e Insieme %	Audit Top Mix (sola lettura)	arena/8c687131-soccermath2-0	pull_request	39266775327	5m47s	1h
completed	success	Registro, tabella Gol - mercato: scala 0-100 per Quote % e Insieme %	Suite test completa	arena/8c687131-soccermath2-0	pull_request	39266775289	28m58s	1h
completed	cancelled	Registro, tabella Gol - mercato: scala 0-100 per Quote % e Insieme %	Suite test completa	arena/8c687131-soccermath2-0	pull_request	39263180751	25m33s	1h
completed	success	Registro, tabella Gol - mercato: scala 0-100 per Quote % e Insieme %	Replay Top Mix legacy (walk-forward, no-leakage)	arena/8c687131-soccermath2-0	pull_request	39263180577	10m50s	1h
completed	success	Registro, tabella Gol - mercato: scala 0-100 per Quote % e Insieme %	Audit Top Mix (sola lettura)	arena/8c687131-soccermath2-0	pull_request	39263180357	5m50s	1h
```
