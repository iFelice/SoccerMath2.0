# Copia congelata del database — 2026-10-29 (commit `331dcd8`)

Questa cartella e' una **copia congelata** di `SoccerMath/database`, presa
dall'albero del commit `331dcd8` (*«Test indipendenti dal database live: fixture
giornata 7 per scheda»*, 2026-10-29 22:16 UTC), con lo strumento di produzione
`db_snapshot.extract_database_at` (`git archive` dell'albero, nessun file
modificato a mano).

## Perche' esiste

Il censimento in `audit/results/referto_fixture_apptest_giornata7_2026-11-02.md`
(punto 4) ha elencato i test del **gruppo 1** — voci 1, 2, 3, 5, 8, 11, 12, 13 —
che sono test del **codice** ma leggono, per sbaglio, dati che cambiano da soli:
i `*_Live.csv` che `update_database.yml` riscrive ogni 6 ore, `live_odds.json`
che `live_odds.yml` riscrive ogni giorno, gli archivi xG che `update_xg.yml`
riscrive due volte a settimana, e `datetime.now()` vero.

Quei test contengono numeri fissi (la finestra da 300 partite del backtest, le
promosse `["Frosinone", "Monza", "Venezia"]`, i 48 abbinamenti della prossima
giornata, le 4 partite del periodo nel fixture AppTest…) misurati su uno stato
preciso del database. Con i file vivi quel legame si rompe al primo giro dei
robot; con **questa copia** e con l'orologio fermo a `ADESSO_CONGELATO`
(2026-10-29 22:00 UTC) il legame torna stabile, **senza cambiare una sola
asserzione**.

## Cosa contiene

Tutti i 38 file regolari di `SoccerMath/database` al commit `331dcd8`
(6,1 MB):

| gruppo | file |
|---|---|
| CSV storici (identici a quelli di oggi) | `<Lega>_2022.csv` … `<Lega>_2025.csv` per le 5 leghe |
| CSV vivi (riscritti dai robot ogni 6 ore) | `Bundesliga_Live.csv`, `LaLiga_Live.csv`, `Ligue1_Live.csv`, `Premier_Live.csv`, `SerieA_Live.csv` |
| quote (riscritte ogni giorno) | `live_odds.json` |
| roster | `season_rosters.json` |
| archivio xG (riscritto 2 volte a settimana) | `xG archivio <lega>.json` (5) |
| medie xG | `xg_<lega>.json` (5) |
| parametri | `parametri_b365_stima_v1.json` |

Ultimo risultato scritto nei CSV vivi della copia: le partite del 2026-10-29
(giornata 9 di Serie A). E' per questo che l'orologio fermo sta alle 22:00 UTC
del 29/10: **dopo** l'ultima partita della copia, cosi' nessun risultato e'
"futuro" e nessuna partita resta da giocare per errore.

## Come si usa

`SoccerMath/test_snapshot_congelato.py`, due context manager che si usano
insieme:

```python
from test_snapshot_congelato import database_congelato, orologio_fermo

with database_congelato(), orologio_fermo():
    ...   # i CSV letti sono questi; datetime.now() e' 2026-10-29 22:00 UTC
```

`database_congelato()` **copia** questa cartella in una cartella temporanea (non
la linka: alcuni test scrivono nel database) e ripunta `config.DATABASE_DIR`,
i percorsi di `config.LEAGUES_CONFIG`, `config.LEAGUE_FILE_MAP`, `xg_archive` e
i due motori Elo — la stessa tecnica di `db_snapshot._redirect`, il modulo di
produzione usato dal replay. Alla fine ripristina tutto.

`orologio_fermo()` ferma `datetime.now()`/`today()`/`utcnow()` nei moduli che
leggono l'ora (`config`, `market_odds`, `lista_giocate`,
`prediction_registry`, `xg_archive`, `season_rosters`, `scheda_partita`, piu'
`app` e i motori Elo se gia' importati, piu' il modulo `datetime` stesso, che
`app.py` rilegge a ogni run di AppTest), ferma `market_odds._adesso_utc` (la
cucitura d'ora di produzione) e allinea le costanti di stagione di `config`.

## Cosa NON e' cambiato

* nessun file di `SoccerMath/database/` (i file vivi restano tali);
* nessuna riga di `app.py`, `scheda_partita.py`, `market_odds.py` o degli altri
  moduli di produzione;
* nessuna asserzione: nei test sono cambiate solo la *sorgente* dei dati e
  l'*ora*.

I controlli che invece **devono** restare sui dati veri (gruppo 2: voci 4, 6, 7,
9, 10 del censimento) non usano questa cartella: girano in
`.github/workflows/controlli_dati.yml` e in `SoccerMath/test_controlli_dati.py`.
