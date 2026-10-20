# Coerenza dei pronostici — verifica finale (PR #80)

**Pull request:** <https://github.com/iFelice/SoccerMath2.0/pull/80> — aperta, *mergeable*, **non** mergiata.
**Branch:** `arena/0a5010c0-soccermath2-0` · **HEAD:** `41465da` (`41465dab7b3cbc6e0ecd8cbd26c3302cad59822b`)
**Data del referto:** 20/10/2026 13:09 CEST (Europe/Rome, `ZoneInfo`)
**Ambito:** sola verifica. **Nessuna modifica al codice**, nessun replay con scrittura, nessuna chiave, nessuna
chiamata di rete dentro i test, nessun merge.

I cinque lavori che precedono questo referto hanno un solo obiettivo: che il *pronostico* mostrato
nelle varie schede sia sempre lo stesso, calcolato con la stessa regola.

---

## 1. Diff rispetto a `main`

```
$ git diff --stat origin/main...HEAD
```

| File | Linee |
| --- | --- |
| `SoccerMath/app.py` | 378 +- |
| `SoccerMath/market_odds.py` | 58 +- |
| `SoccerMath/prediction_registry.py` | 29 +- |
| `SoccerMath/scheda_partita.py` | 15 + |
| `SoccerMath/test_apptest_multiple_riquadri.py` | 32 +- |
| `SoccerMath/test_apptest_scheda_partita.py` | 24 +- |
| `SoccerMath/test_apptest_scheda_pronostici.py` | 47 +- |
| `SoccerMath/test_apptest_selezione_tabelle.py` | 4 +- |
| `SoccerMath/test_calendario_cache_errori.py` | 190 + (nuovo) |
| `SoccerMath/test_multiple_pronostico_partita.py` | 366 + (nuovo) |
| `SoccerMath/test_pareggi_soglia.py` | 300 + (nuovo) |
| `SoccerMath/test_pronostico_partite.py` | 263 + (nuovo) |
| `SoccerMath/test_quote_live.py` | 28 +- |
| `SoccerMath/test_registry_tracking.py` | 12 +- |
| `SoccerMath/test_rifiniture_registro.py` | 9 +- |
| `SoccerMath/test_topmix_mercato.py` | 61 +- |
| `SoccerMath/test_topmix_ombra_totali.py` | 12 +- |
| `SoccerMath/test_versione_selettore.py` | 7 +- |
| `audit/replay_topmix_mercato.py` | 113 +- |
| `audit/test_replay_topmix_mercato.py` | 30 +- |
| `audit/test_topmix_registry_tracking.py` | 10 +- |

**21 file cambiati, 1803 inserimenti, 185 rimozioni.** A questi si aggiunge questo stesso referto,
che entra con il commit di verifica.

Cronologia del branch rispetto a `main` (`git log --oneline origin/main..HEAD`):

```
41465da Multiple: il pronostico della partita accanto all'esito giocato
a2c60eb Pareggi: solo i pareggi con almeno il 30% (nuova SOGLIA_PAREGGI)
d27873d Partite: il pronostico è quello del Top Mix (sotto il 57% un trattino)
705c93c Soglia del pronostico di mercato 0,55 -> 0,57: selettore topmix_mercato_v4
10dab07 Calendario: in cache solo le risposte riuscite, l'errore si ritenta al rerun
```

---

## 2. (a) Impronte del selettore con Python 3.11

Confronto eseguito con **Python 3.11.2** (`.venv` del repository) lanciando un interprete *separato*
dentro ogni albero: il branch in `/home/user/SoccerMath2.0/SoccerMath` e un worktree distaccato su
`origin/main` (`daa978a`) in `/tmp/sm_main/SoccerMath`. Lo script di confronto
(`/home/user/impronte_confronto.py`, fuori dal repository per non sporcare `git status`) legge
`SELECTOR_VERSION_CURRENT`, `IMPRONTE`, `IMPRONTE_OU` e ricalcola `impronta_attuale()` e
`impronta_ou_attuale()`.

| Voce | `main` (`daa978a`) | branch (`41465da`) | Esito |
| --- | --- | --- | --- |
| `SELECTOR_VERSION_CURRENT` | `topmix_mercato_v3` | `topmix_mercato_v4` | avanzamento atteso |
| `impronta_attuale()` | `1d2787b0f45b0f91a6ba651809b6e9ecdb2ba7dec35972dafdb40814186a4bb5` | `01aaa65657c38e0994986a5f75efb0b4976aa30338057faf3efd566203fd0cad` | **COINCIDE** con `IMPRONTE["topmix_mercato_v4"]` |
| `impronta_ou_attuale()` | `fbb0cb99c42e589c3296a8bc4185c7f5b284bc3d1a67b7e621dabc7517431d8c` | `fbb0cb99c42e589c3296a8bc4185c7f5b284bc3d1a67b7e621dabc7517431d8c` | **IDENTICA** |
| `IMPRONTE` (1X2) | — | `[topmix_1x2_gate025_ens06_v2, topmix_mercato_v3, topmix_mercato_v4]` | append-only rispettata |

Controlli aggiuntivi riusciti:

- l'impronta di `main` (`1d2787b0…`) è **ancora presente** nella tabella del branch: le righe già
  registrate con la versione v3 non sono state toccate e continuano a essere risolvibili;
- `impronta_ou_attuale()` è uguale su `main` e sul branch e corrisponde a `IMPRONTE_OU["totals_mercato_v1"]`:
  il selettore dei totali (Over/Under) non cambia, quindi i pronostici sui totali già registrati restano
  coerenti con quelli nuovi.

---

## 3. (b) Suite completa a lotti

Ogni lotto è stato lanciato con `timeout 900` (15 minuti), come richiesto; nessun lotto ha superato il
limite. Comando tipo:

```
timeout 900 /home/user/SoccerMath2.0/.venv/bin/python -m pytest <moduli del lotto> -q
```

| Lotto | Contenuto | Esito | Tempo |
| --- | --- | --- | --- |
| L1 | `test_apptest_calendario_leghe.py`, `test_elo_ensemble_1x2.py` | `25 passed, 947 subtests passed` | 300.29s |
| L2 | 4 moduli `test_apptest_*` (multipla, multiple_riquadri, navigazione, topmix_presentazione) + `test_multiple_pronostico_partita.py`, `test_pareggi_soglia.py`, `test_pronostico_partite.py` | `78 passed, 1 skipped, 424 subtests passed` | 446.76s |
| L3 | 5 moduli `test_apptest_*` (scheda_partita, scheda_pronostici, selezione_tabelle, top_mix, totals_mercato) + `test_scheda_partita.py`, `test_tabelle_sigle_percentuali.py` | `132 passed, 1 skipped, 796 subtests passed` | 674.88s |
| L4 | 19 moduli unitari `SoccerMath` (da `alias_quote_live` a `presentazione_topmix`) | `365 passed, 11 subtests passed` | 67.05s |
| L5 | 35 moduli `SoccerMath` (da `problemi_produzione` a `xg_pipeline`) | `925 passed, 4811 subtests passed` | 97.00s |
| L6 | cartella `audit/` (52 moduli) | `870 passed, 6 skipped, 1 warning, 51 subtests passed` | 204.42s |

Totali:

- **`SoccerMath`: 1525 passed, 2 skipped, 6989 subtests** (L1+L2+L3+L4+L5) — identico, test per test,
  all'esecuzione in processo singolo già fatta prima di questo referto (`1525 passed, 2 skipped,
  6989 subtests passed in 895.24s`); i lotti costano di più in secondi perché ogni processo
  ricarica da zero l'app con `AppTest`;
- **`audit`: 870 passed, 6 skipped, 51 subtests** (L6), con un solo warning (niente errori);
- `SoccerMath/test_theme_toggle.py` eseguito **come script**, come in CI: 4 test eseguiti,
  `exit 0`, ultima riga `🎉 TUTTI I TEST PASSATI` (con `pytest` darebbe `INTERNALERROR … SystemExit: 0`,
  perché non è un test pytest).

Nessun test è stato escluso: la somma dei lotti copre tutti i file `test_*.py` tracciati.

---

## 4. (c) Stato del repository e della CI

```
$ git status --porcelain
$          # nessuna riga: albero di lavoro pulito
```

Un solo `gh run list`, filtrato sul branch della PR
(`gh run list --branch arena/0a5010c0-soccermath2-0 --limit 10`), eseguito alle 12:36 CEST:

| Workflow | Esito | Durata | Quando |
| --- | --- | --- | --- |
| Replay Top Mix legacy | success | 10m33s | ~1h fa |
| **Suite test completa** | **cancelled** | **30m7s** | ~1h fa |
| Audit Top Mix (sola lettura) | success | 4m42s | ~1h fa |
| Quote live | success | 15s | ~1h fa |
| (gruppo precedente: Replay 10m25s, Audit 4m48s, **Suite 28m53s**, Quote live 16s) | success | — | ~5h fa |
| (gruppo ancora precedente: Suite 27m0s, Replay, Audit, Quote live) | success | — | ~15h fa |

**Nota onesta sulla Suite test completa cancellata.** Non è una regressione: lo stesso codice passa
tutto in locale (§3). Il job ha `timeout-minutes: 30` e il run si è fermato a 30m7s, cioè ha raggiunto
il tetto del job; i due run completati prima avevano impiegato 28m53s e 27m0s, quindi il margine era di
pochi minuti. Il motivo è strutturale: `.github/workflows/test_suite.yml` lancia **un processo pytest
per ogni file** di test (`git ls-files`), e ogni processo paga da solo import e avvio di `AppTest`;
nella stessa macchina un'unica invocazione di pytest su `SoccerMath` chiude in ~15 minuti. Con i quattro
nuovi file di test il totale è salito oltre la mezz'ora. Non rientra in questo lavoro (sola verifica,
nessuna modifica al codice): va deciso a parte se alzare `timeout-minutes` o accorpare i moduli in
pochi invocazioni, come fatto qui in locale.

Gli altri tre workflow del branch (Replay Top Mix legacy, Audit Top Mix in sola lettura, Quote live)
sono verdi sull'ultimo commit.

---

## 5. Cosa rende coerenti i pronostici (riepilogo dei cinque lavori)

1. **Una sola soglia, un solo posto.** `market_odds.SOGLIA_TOPMIX_MERCATO = 0.57` (era 0.55, prima
   ancora un valore scritto a mano in più punti) e `SOGLIA_PAREGGI = 0.30` per i pareggi: nessun
   numero è più ripetuto dentro `app.py`.
2. **La stessa regola in tutte le schede.** Top Mix, «Partite», «Pareggi» e «Multiple» usano lo stesso
   valore: sopra la soglia il pronostico è quello del Top Mix, sotto la soglia compare un trattino
   («Partite») o la riga non entra in classifica («Pareggi»). Nelle «Multiple» l'esito giocato e il
   pronostico della partita stanno uno accanto all'altro (`12 (pronostico: 1)`): se coincidono, la
   parentesi non si scrive.
3. **Versione del selettore avanzata a `topmix_mercato_v4`** con la nuova impronta: le righe già
   registrate con v3 restano leggibili e non vengono riscritte (tabella append-only).
4. **Il selettore dei totali non è cambiato** (impronta Over/Under identica su `main` e sul branch):
   i pronostici sui totali già salvati restano confrontabili con quelli nuovi.
5. **Il calendario in cache memorizza solo le risposte riuscite**: un errore di rete non resta
   congelato in cache e al rerun successivo si ritenta (nessun pronostico calcolato su dati vuoti).

---

## 6. Come ripetere la verifica

```bash
# impronte (serve un worktree su origin/main)
git worktree add --detach /tmp/sm_main origin/main
python /home/user/impronte_confronto.py /tmp/sm_main/SoccerMath

# suite a lotti (timeout 900 per lotto)
cd SoccerMath && timeout 900 .venv/bin/python -m pytest <moduli> -q

# test_theme_toggle come script
cd SoccerMath && .venv/bin/python test_theme_toggle.py
```

Ambiente: Python 3.11.2, pytest 9.1.1, streamlit 1.66.0 (`SoccerMath/requirements.txt` +
`requirements-audit.txt`). I test non usano la rete e non scrivono nel Registro.
