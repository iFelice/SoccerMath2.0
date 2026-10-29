# Fixture giornata 7 — Serie A fino al 19/10/2026

Copia congelata dei soli dati che servono ai test di scheda (Napoli-Roma)
per renderli indipendenti dal database live che i robot aggiornano ogni giorno.

* `SerieA_Live.csv` — 70 partite (71 righe con header) fino alla giornata 7
  (ultima: Parma-Torino 0-3 del 19/10/2026), presa da `87e9628:SoccerMath/database/SerieA_Live.csv`
  (merge PR #81, commit 91d62b6 — giorno in cui i test `test_scheda_grafica.py`
  e `test_scheda_partita.py` sono stati scritti, con Napoli 9ª era 8ª, 10 punti,
  7 giocate, 31 giornate rimaste, 17 punti Roma, frase titolo/Europa ecc.).

* `live_odds.json` — snapshot delle quote dello stesso giorno
  (`87e9628:SoccerMath/database/live_odds.json`, `generato_il` 2026-10-20T13:36:08Z,
  20 eventi Serie A). Il test `test_scheda_grafica` non legge le quote dal file
  (usa `EVENTO_NAPOLI_ROMA` fisso), ma la fixture è conservata per completezza
  e per futuri test che dovessero averne bisogno.

I numeri attesi nei test (Napoli 9 era 8, 10 punti, 7 giocate, 31 rimaste,
"In corsa per l'Europa: 3 punti dal sesto posto", "In corsa per il titolo:
2 punti dal primo posto" ecc.) restano quelli verificati su questo snapshot;
i test leggono `SerieA_Live.csv` via `carica_risultati_stagione(..., percorso=FIXTURE_CSV)`
come già fanno altri test del progetto con snapshot pinnati (`snap_test.py`).

Nessuna modifica all'app: solo i test puntano a questa copia.
