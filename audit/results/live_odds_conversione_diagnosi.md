# Quote live: perche' `live_odds.json` e' uscito con `libri: []`

Generato il 2026-10-09T17:53:22Z da `audit/diagnose_live_odds_conversione.py`. Sola lettura, **nessuna chiamata all'API, 0 crediti**: usa solo dati committati (gli snapshot della sonda del 2026-10-08 e il file di produzione del 2026-10-09).

## 1. Esito: la risposta aveva i bookmaker, li ha persi la conversione

Le risposte reali della sonda passate nella funzione di produzione che costruisce `libri` (`update_live_odds.libri_dell_evento`), nelle due forme in cui la stessa risposta puo' presentarsi:

| lega | eventi | libri (forma compattata della sonda) | libri (forma grezza dell'API) con il codice PRECEDENTE | libri (forma grezza dell'API) con il codice di OGGI |
|---|---|---|---|---|
| Serie A | 20 | 679 | 0 | 679 |
| Premier League | 20 | 717 | 0 | 717 |
| La Liga | 20 | 630 | 0 | 630 |
| Bundesliga | 18 | 625 | 0 | 625 |
| Ligue 1 | 18 | 576 | 0 | 576 |
| **totale** | 96 | 3227 | 0 | 3227 |

Gli snapshot committati della sonda **non sono il corpo della risposta**: sono la forma COMPATTATA prodotta da `live_odds_probe.compact_events`, che ha gia' ridotto `bookmakers[].markets[].outcomes[]` a `{"h2h": {"home": ..., "draw": ..., "away": ...}}`. Passati cosi' com'erano nella funzione di produzione danno libri PIENI, anche con il codice precedente: e' per questo che il dry-run della PR passava mentre la produzione scriveva il vuoto.

La stessa risposta nella forma GREZZA dell'API — quella che arriva dalla rete, ricostruita da `audit/live_odds_raw_fixtures.py` e verificata per andata e ritorno in `audit/test_live_odds_raw_fixtures.py` — con il codice precedente da **0 libri su tutti gli eventi**: esattamente il file del 2026-10-09.

### La riga esatta

`SoccerMath/update_live_odds.py:147-149` (commit `bcbeb74`):

```python
    for libro in evento.get("bookmakers") or []:
        if not isinstance(libro, dict):
            continue
        h2h = libro.get("h2h")          # 147
        if not isinstance(h2h, dict):   # 148  <-- scarta ogni bookmaker dell'API
            continue                    # 149
```

**Perche'.** The Odds API non manda `h2h` dentro il bookmaker: manda `bookmakers[].markets[]`, e il mercato `h2h` ha `outcomes[]` con `name` e `price`. `libro.get("h2h")` e' quindi `None`, `isinstance(None, dict)` e' falso e il `continue` butta il bookmaker. Tutti. In silenzio: nessun errore, nessun conteggio, HTTP 200, 1 credito speso per lega e `n_eventi` giusto, per cui il log diceva "20 eventi OK" e il workflow usciva `success`.

Le altre cause possibili sono state controllate e **scartate**:

* filtro sulle chiavi dei bookmaker: non esiste, non c'e' nessuna lista di bookmaker ammessi ne' nel writer ne' nella richiesta;
* nomi degli esiti: nella risposta gli esiti si chiamano come le squadre dell'evento piu' `Draw`; il confronto con i nomi normalizzati del progetto avviene DOPO, in `market_odds.indice_partite`, e oggi abbina 96 eventi su 96;
* tipo dei prezzi: nella sonda tutti i 3227 prezzi sono `float` validi;
* parametri della richiesta: vedi il punto 2, la differenza c'e' ma non spiega lo zero.

## 2. Parametri: produzione contro sonda

| parametro | produzione (2026-10-09) | sonda (2026-10-08) |
|---|---|---|
| endpoint | /v4/sports/<sport_key>/odds | /v4/sports/<sport_key>/odds |
| regions | eu | eu,uk |
| markets | h2h | h2h |
| oddsFormat | decimal | decimal |
| bookmakers | (parametro non usato) | (parametro non usato) |
| dateFormat | iso | iso |
| costo_per_lega | 1 | 2 |

L'unica differenza e' `regions`: la produzione chiede `eu` (1 credito a chiamata), la sonda chiedeva `eu,uk` (2 crediti). `eu` e' un SOTTOINSIEME di `eu,uk`: puo' ridurre il numero di bookmaker per evento, non azzerarlo. Nella sonda, sugli stessi eventi, compaiono bookmaker che non sono del Regno Unito — `pinnacle`, `unibet_nl`, `winamax_fr`, `winamax_de`, `betclic_fr`, `codere_it`, `tipico_de`, `betsson`, `nordicbet`, `onexbet` — quindi con `regions=eu` i libri restano diversi da zero. Endpoint, `markets`, `oddsFormat` e `dateFormat` sono identici e non esiste un parametro `bookmakers` nella richiesta.

## 3. Il file del 2026-10-09 e gli stessi eventi nella sonda

| lega | HTTP | crediti | eventi | libri nel file | eventi in comune con la sonda | libri che la sonda aveva su quegli eventi | minimo libri/evento nella sonda |
|---|---|---|---|---|---|---|---|
| Serie A | 200 | 1 | 20 | 0 | 20 | 679 | 28 |
| Premier League | 200 | 1 | 20 | 0 | 20 | 717 | 29 |
| La Liga | 200 | 1 | 20 | 0 | 20 | 630 | 25 |
| Bundesliga | 200 | 1 | 18 | 0 | 18 | 625 | 29 |
| Ligue 1 | 200 | 1 | 18 | 0 | 18 | 576 | 27 |

Tutti e 96 gli eventi del file guasto hanno lo STESSO `id` degli eventi della sonda del giorno prima, e su quegli eventi la sonda aveva da 25 a 41 bookmaker ciascuno. La fonte quotava quelle partite; il file no.

## 4. Il calendario della sonda dopo la riparazione

Prossima giornata con la regola di produzione (prima partita futura rispetto all'istante della sonda 2026-10-08T23:30:38+00:00 piu' finestra di 5 giorni, `app.TOP_MIX_ROUND_WINDOW_DAYS`), quote prese dal file prodotto dal writer riparato e lette con `carica_quote_live` -> `indice_partite` -> `cerca_quote` -> `probabilita_mercato`:

| lega | partite della giornata | con quote (Pinnacle) | con quote (media libri) | senza quote |
|---|---|---|---|---|
| Serie A | 10 | 10 | 0 | 0 |
| Premier League | 10 | 10 | 0 | 0 |
| La Liga | 10 | 10 | 0 | 0 |
| Bundesliga | 9 | 9 | 0 | 0 |
| Ligue 1 | 9 | 9 | 0 | 0 |
| **totale** | 48 | 48 | 0 | 0 |

Nomi non abbinati dal resolver di produzione: 0.

## 5. Cosa e' stato cambiato

* `update_live_odds.h2h_dal_bookmaker` accetta ENTRAMBE le forme (grezza dell'API e compattata della sonda) e dichiara il motivo di ogni scarto;
* il giro FALLISCE con uscita 4 se una lega ha eventi e zero libri, e in quel caso il file precedente non viene toccato;
* il log per lega riporta eventi, eventi con almeno un libro, eventi con Pinnacle e bookmaker nella risposta grezza; "N eventi OK" non esiste piu';
* il file porta per ogni lega i conteggi grezzi pre-conversione (eventi, bookmaker distinti per chiave, mercati presenti) e quelli post-conversione, cosi' il prossimo guasto si legge dal file senza spendere crediti.

