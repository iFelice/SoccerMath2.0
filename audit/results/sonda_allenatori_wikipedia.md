# Sonda allenatori — fonte alternativa: Wikipedia (sola lettura)

**Sonda non eseguita: nessuna richiesta a Wikipedia.** Questo referto dichiara la regola e i casi pubblici; le colonne «su Wikipedia» sono «da misurare». Lo misura il workflow `audit_allenatori.yml`, job «Sonda allenatori Wikipedia».

Run: **2026-10-13T16:42:00Z** · lingua: **en** (en.wikipedia.org) · stagione: **2026–27** · richieste API: **0**.

## Regola dichiarata (prima dei numeri)

La regola si valuta solo se **tutte e 5 le leghe** sono state lette per intero (tabella «Managerial changes» trovata e tutte le righe lette). Altrimenti: «non valutabile: leghe mancanti <elenco>», senza giudizio.

Con le 5 leghe lette, la regola **passa** solo se **tutti** i casi pubblici di `casi_pubblici_2026_27.json` (almeno 3 valutabili) risultano presenti nella tabella di Wikipedia **con l'allenatore entrante giusto**. La data non e' parte della regola: le differenze sono riportate a parte. I cambi su Wikipedia che non sono nel file dei casi sono elencati in fondo, senza giudizio.

Esito di questo run: **NON VALUTABILE** — sonda non eseguita.

## Leghe lette

| Lega | Letta per intero | Titolo pagina | Revisione | Righe lette | Non lette | Nota |
|---|---|---|---|---|---|---|
| Serie A | da misurare | — | — | — | — | — |
| Premier League | da misurare | — | — | — | — | — |
| La Liga | da misurare | — | — | — | — | — |
| Bundesliga | da misurare | — | — | — | — | — |
| Ligue 1 | da misurare | — | — | — | — | — |

## Casi pubblici su Wikipedia

| Lega | Squadra | Entrante (file) | Entrante (Wikipedia) | Data file | Data Wikipedia | Data coincide | Esito |
|---|---|---|---|---|---|---|---|
| Serie A | Fiorentina | Paolo Vanoli | — | 2026-09-06 | — | — | **da misurare** |
| Serie A | Bologna | Raffaele Palladino | — | 2026-09-27 | — | — | **da misurare** |
| Serie A | Parma | Alberto Gilardino | — | 2026-09-27 | — | — | **da misurare** |
| Bundesliga | Borussia Mönchengladbach | Alexander Blessin | — | 2026-09-22 | — | — | **da misurare** |
| Ligue 1 | Lens | Yannick Cahuzac | — | 2026-09-15 | — | — | **da misurare** |
| La Liga | Osasuna | Jagoba Arrasate | — | 2026-10-12 | — | — | **da misurare** |

## Cambi su Wikipedia che NON sono nel file dei casi

_Nessuno (o leghe non lette)._

## Come e' stata prodotta questa sonda

* API MediaWiki (`action=parse`, `prop=text|revid`), una pagina per lega, pagina `2026–27_<lega>` in inglese; titolo alternativo con trattino `-` se il primo non esiste;
* User-Agent dichiarato: `SoccerMath2.0-audit/1.0 (https://github.com/iFelice/SoccerMath2.0; sonda di sola lettura dei cambi di allenatore; nessuna chiave)`; nessuna chiave; una richiesta alla volta, pausa 1 s, `maxlag=5`, al massimo 3 nuovi tentativi su 429/5xx;
* sola lettura: nessuna scrittura in `SoccerMath/`, nessuna modifica all'app.
