# Sonda allenatori (football-data.org v4, sola lettura)

**Run di PROVA con risposte FINTA (`--fixture`)**: quello che segue mostra che il giro funziona, NON lo stato delle API. Il run vero lo esegue il workflow manuale `audit_allenatori.yml`.

Run: **2026-10-13T10:31:18Z** · stagione dal run: **predefinita** · chiamate fatte: **0**.

## Regola dichiarata (prima dei numeri)

L'allenatore entra nella scheda partita **solo se**:

1. la copertura delle squadre con allenatore e' almeno **95%** (83.3% in questo run);
2. **tutti** i casi di cambio allenatore verificati su fonti pubbliche risultano aggiornati nelle API (nessun caso «non aggiornato», nessun caso «da verificare»).

Esito di questo run: **NON AFFIDABILE** — motivi: copertura 83.3% < 95%; 4 casi su 6 non aggiornati. Se non e' affidabile la scheda NON mostra l'allenatore e lo dichiara, rimandando alle fonti alternative (sito del club, comunicati ufficiali).

## Copertura (squadre con un allenatore nella risposta)

| Lega | Squadre | Con allenatore | Senza |
|---|---|---|---|
| Serie A | 4 | 3 | 1 |
| Premier League | 0 | 0 | 0 |
| La Liga | 0 | 0 | 0 |
| Bundesliga | 2 | 2 | 0 |
| Ligue 1 | 0 | 0 | 0 |
| **totale** | **6** | **5** | **1** |

Squadre senza allenatore nella risposta: Serie A: Senza Mister.

## Formato delle date di contratto

* fine: mese: 3 campi.
* inizio: mese: 3 campi.

Le date sono salvate **come arrivano** (nessun giorno inventato): `contract.start` e `contract.until` restano le stringhe della fonte, la forma e' dichiarata campo per campo.

## Casi pubblici 2026/27: le API sono aggiornate?

I casi vengono da `audit/data/allenatori/casi_pubblici_2026_27.json` (versione casi_allenatori_2026_27_v1, 2026-10-13; solo i casi «verificabili»: un esonero senza sostituto certo non e' un caso, e' una nota).

* **Valencia** non e' un caso: Carlos Corberan esonerato il 13/09/2026 (fonte: https://www.rtve.es/deportes/20260913/valencia-destiutcion-carlos-corberan-entrenador-ceo-cupula-directiva-futbol/17223177.shtml), ma le fonti consultate danno un tecnico ad interim (Oscar Sanchez, Mestalla) senza un sostituto definitivo certo: senza l'entrante il confronto con le API non direbbe nulla, quindi il caso NON e' conteggiato.
* **Premier League** non e' un caso: nessun esonero in Premier League 2026/27 al 09/10/2026 (fonti: https://www.footballtransfers.com/en/transfer-news/uk-premier-league/2021/10/what-managers-have-been-sacked-this-season del 06/10/2026 e la pagina BBC "Manager ins and outs - 2026-27", in cui non compare nessun cambio di panchina di Premier fino al 10/10/2026): per la Premier non c'e' un caso da verificare, e' il risultato stesso.

Casi verificabili in questo run: **6** (servono almeno 3 casi e che TUTTI risultino aggiornati).

| Lega | Squadra | Uscente | Entrante | Data | Allenatore nelle API | Esito | Fonte |
|---|---|---|---|---|---|---|---|
| Serie A | Fiorentina | Fabio Grosso | Paolo Vanoli | 2026-09-06 | Fabio Grosso | **non aggiornato** | [fonte](https://sport.sky.it/calcio/serie-a/serie-a-2026-2027-allenatori-esonerati) |
| Serie A | Bologna | Domenico Tedesco | Raffaele Palladino | 2026-09-27 | — | **squadra non nel run** | [fonte](https://sport.sky.it/calcio/serie-a/serie-a-2026-2027-allenatori-esonerati) |
| Serie A | Parma | Carlos Cuesta | Alberto Gilardino | 2026-09-27 | Alberto Gilardino | **aggiornato** | [fonte](https://www.corrieredellosport.it/news/calcio/serie-a/parma/2026/09/29-151546958/parma_gilardino_il_nuovo_allenatore_ora_ufficiale) |
| Bundesliga | Borussia Mönchengladbach | Eugen Polanski | Alexander Blessin | 2026-09-22 | Alexander Blessin | **aggiornato** | [fonte](https://www.bundesliga.com/de/bundesliga/news/alexander-blessin-gladbach-trainer-fix-nachfolger-eugen-polanski-39297) |
| Ligue 1 | Lens | Dino Toppmöller | Yannick Cahuzac | 2026-09-15 | — | **squadra non nel run** | [fonte](https://www.franceinfo.fr/sports/foot/rc-lens/ligue-1-yannick-cahuzac-restera-l-entraineur-de-lens-au-dela-du-match-a-monaco_8197349.html) |
| La Liga | Osasuna | Luis Miguel Ramis | Jagoba Arrasate | 2026-10-12 | — | **squadra non nel run** | [fonte](https://www.infobae.com/america/agencias/2026/10/12/el-osasuna-espanol-destituye-a-su-entrenador-luis-miguel-ramis-y-jagoba-arrasate-vuelve/) |

* Fiorentina: l'API riporta ancora l'uscente (Fabio Grosso); atteso: Paolo Vanoli.
* Parma: l'API riporta l'entrante (Alberto Gilardino).
* Borussia Mönchengladbach: l'API riporta l'entrante (Alexander Blessin).

## Come e' stata prodotta questa sonda

* `GET /v4/competitions/{codice}/teams` (una chiamata per lega) e `GET /v4/teams/{id}` (una per squadra): e' da quest'ultima che arrivano `coach.name`, `coach.contract.start` e `coach.contract.until`;
* chiave nell'header `X-Auth-Token`, **mai** nell'URL, mai stampata; massimo **10 chiamate al minuto** (limite del piano gratuito), con finestra mobile;
* sola lettura: nessuna scrittura in `SoccerMath/`, nessuna modifica all'app, nessuna chiamata fatta dall'app;
