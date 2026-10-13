# Sonda allenatori (football-data.org v4, sola lettura)

Run: **2026-10-13T17:23:03Z** · stagione dal run: **predefinita** · chiamate fatte: **101**.

## Regola dichiarata (prima dei numeri)

L'allenatore entra nella scheda partita **solo se**:

0. **tutte e 5 le leghe** sono state lette per intero (ogni squadra della lega ha la sua risposta). Se una lega manca, la regola NON si valuta: nessuna percentuale viene confrontata con la soglia;
1. la copertura delle squadre con allenatore e' almeno **95%**;
2. **tutti** i casi di cambio allenatore verificati su fonti pubbliche risultano aggiornati nelle API (nessun caso «non aggiornato», nessun caso «da verificare»). Un caso «squadra non nel run» NON conta né come aggiornato né come non aggiornato; servono almeno 3 casi valutabili.

Esito di questo run: **NON AFFIDABILE** — motivi: 5 casi su 6 non aggiornati. Se non e' affidabile la scheda NON mostra l'allenatore e lo dichiara, rimandando alle fonti alternative (sito del club, comunicati ufficiali).

## Copertura (squadre con un allenatore nella risposta)

| Lega | Squadre | Con allenatore | Senza | Letta per intero |
|---|---|---|---|---|
| Serie A | 20 | 20 | 0 | sì |
| Premier League | 20 | 20 | 0 | sì |
| La Liga | 20 | 20 | 0 | sì |
| Bundesliga | 18 | 18 | 0 | sì |
| Ligue 1 | 18 | 17 | 1 | sì |
| **totale** | **96** | **95** | **1** |

Squadre senza allenatore nella risposta: Ligue 1: Stade Brestois 29.

## Formato delle date di contratto

_Nessuna data di contratto nella risposta._

Le date sono salvate **come arrivano** (nessun giorno inventato): `contract.start` e `contract.until` restano le stringhe della fonte, la forma e' dichiarata campo per campo.

## Casi pubblici 2026/27: le API sono aggiornate?

I casi vengono da `audit/data/allenatori/casi_pubblici_2026_27.json` (versione casi_allenatori_2026_27_v1, 2026-10-13; solo i casi «verificabili»: un esonero senza sostituto certo non e' un caso, e' una nota).

* **Valencia** non e' un caso: Carlos Corberan esonerato il 13/09/2026 (fonte: https://www.rtve.es/deportes/20260913/valencia-destiutcion-carlos-corberan-entrenador-ceo-cupula-directiva-futbol/17223177.shtml), ma le fonti consultate danno un tecnico ad interim (Oscar Sanchez, Mestalla) senza un sostituto definitivo certo: senza l'entrante il confronto con le API non direbbe nulla, quindi il caso NON e' conteggiato.
* **Premier League** non e' un caso: nessun esonero in Premier League 2026/27 al 09/10/2026 (fonti: https://www.footballtransfers.com/en/transfer-news/uk-premier-league/2021/10/what-managers-have-been-sacked-this-season del 06/10/2026 e la pagina BBC "Manager ins and outs - 2026-27", in cui non compare nessun cambio di panchina di Premier fino al 10/10/2026): per la Premier non c'e' un caso da verificare, e' il risultato stesso.

Casi nel file: **6**; valutabili in questo run: **6** (servono almeno 3 casi valutabili e che TUTTI risultino aggiornati). L'età è in giorni fra la data del cambio e il giorno del run.

| Lega | Squadra | Uscente | Entrante | Data | Età (giorni) | Allenatore nelle API | Esito | Fonte |
|---|---|---|---|---|---|---|---|---|
| Serie A | Fiorentina | Fabio Grosso | Paolo Vanoli | 2026-09-06 | 37 | Fabio Grosso | **non aggiornato** | [fonte](https://sport.sky.it/calcio/serie-a/serie-a-2026-2027-allenatori-esonerati) |
| Serie A | Bologna | Domenico Tedesco | Raffaele Palladino | 2026-09-27 | 16 | Domenico Tedesco | **non aggiornato** | [fonte](https://sport.sky.it/calcio/serie-a/serie-a-2026-2027-allenatori-esonerati) |
| Serie A | Parma | Carlos Cuesta | Alberto Gilardino | 2026-09-27 | 16 | Carlos Cuesta | **non aggiornato** | [fonte](https://www.corrieredellosport.it/news/calcio/serie-a/parma/2026/09/29-151546958/parma_gilardino_il_nuovo_allenatore_ora_ufficiale) |
| Bundesliga | Borussia Mönchengladbach | Eugen Polanski | Alexander Blessin | 2026-09-22 | 21 | Eugen Polański | **non aggiornato** | [fonte](https://www.bundesliga.com/de/bundesliga/news/alexander-blessin-gladbach-trainer-fix-nachfolger-eugen-polanski-39297) |
| Ligue 1 | Lens | Dino Toppmöller | Yannick Cahuzac | 2026-09-15 | 28 | Yannick Cahuzac | **aggiornato** | [fonte](https://www.franceinfo.fr/sports/foot/rc-lens/ligue-1-yannick-cahuzac-restera-l-entraineur-de-lens-au-dela-du-match-a-monaco_8197349.html) |
| La Liga | Osasuna | Luis Miguel Ramis | Jagoba Arrasate | 2026-10-12 | 1 | Luis Ramis | **non aggiornato** | [fonte](https://www.infobae.com/america/agencias/2026/10/12/el-osasuna-espanol-destituye-a-su-entrenador-luis-miguel-ramis-y-jagoba-arrasate-vuelve/) |

* Fiorentina: l'API riporta ancora l'uscente (Fabio Grosso); atteso: Paolo Vanoli.
* Bologna: l'API riporta ancora l'uscente (Domenico Tedesco); atteso: Raffaele Palladino.
* Parma: l'API riporta ancora l'uscente (Carlos Cuesta); atteso: Alberto Gilardino.
* Borussia Mönchengladbach: l'API riporta ancora l'uscente (Eugen Polanski); atteso: Alexander Blessin.
* Lens: l'API riporta l'entrante (Yannick Cahuzac).
* Osasuna: l'API riporta ancora l'uscente (Luis Miguel Ramis); atteso: Jagoba Arrasate.

## Come e' stata prodotta questa sonda

* `GET /v4/competitions/{codice}/teams` (una chiamata per lega) e `GET /v4/teams/{id}` (una per squadra): e' da quest'ultima che arrivano `coach.name`, `coach.contract.start` e `coach.contract.until`;
* chiave nell'header `X-Auth-Token`, **mai** nell'URL, mai stampata;
* sola lettura: nessuna scrittura in `SoccerMath/`, nessuna modifica all'app, nessuna chiamata fatta dall'app;
* limite: al massimo **10 richieste in qualunque finestra di 60 secondi**, contando anche l'elenco squadre; header `X-Requests-Available-Minute` e `X-RequestCounter-Reset` letti quando presenti;
* su 429: attesa del tempo dell'header `X-RequestCounter-Reset` (o 60 s) e un nuovo tentativo, **al massimo 3 per chiamata**;
* richieste fatte: **101** (di cui ripetute dopo un 429: 0); attese per il limite: 41; attese dopo un 429: 0; attese per header di quota: 10;
* durata minima teorica di queste richieste senza 429: **9 min 6 s**; durata reale del run: **10 min 1 s**;
