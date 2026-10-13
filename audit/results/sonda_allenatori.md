# Sonda allenatori (football-data.org v4, sola lettura)

**Sonda non eseguita: nessuna chiamata reale a football-data.org.** Questo referto dichiara la regola e i casi pubblici raccolti con la fonte; la colonna «Allenatore nelle API» e' «da misurare» perche' nessuno l'ha ancora letta. Nessun numero qui e' un risultato.

Referto generato il **2026-10-13T11:16:49Z** in modalita' «non eseguita» (`--referto-non-eseguito`): nessuna chiave API usata, nessuna cartella di snapshot creata, nessun file `audit/data/allenatori/<giorno>.json` scritto.

## Regola dichiarata (prima dei numeri)

L'allenatore entra nella scheda partita **solo se**:

1. la copertura delle squadre con allenatore e' almeno **95%** (misurata su tutte e cinque le leghe);
2. **tutti** i casi di cambio allenatore verificati su fonti pubbliche risultano gia' aggiornati nelle API (nessun caso fuori posto).

Finche' non gira un run reale la regola **non e' soddisfatta**: la scheda partita non mostra l'allenatore e lo dichiara, rimandando alle fonti alternative (sito del club, comunicati ufficiali). Un run `--fixture` (risposte finte) non cambia questa riga: i suoi file portano il prefisso `fixture_` e non valgono come misura.

## Casi pubblici 2026/27 (fonte per caso; stato da misurare)

I casi vengono da `audit/data/allenatori/casi_pubblici_2026_27.json` (versione casi_allenatori_2026_27_v1, 2026-10-13).

* **Valencia** non e' un caso: Carlos Corberan esonerato il 13/09/2026 (fonte: https://www.rtve.es/deportes/20260913/valencia-destiutcion-carlos-corberan-entrenador-ceo-cupula-directiva-futbol/17223177.shtml), ma le fonti consultate danno un tecnico ad interim (Oscar Sanchez, Mestalla) senza un sostituto definitivo certo: senza l'entrante il confronto con le API non direbbe nulla, quindi il caso NON e' conteggiato.
* **Premier League** non e' un caso: nessun esonero in Premier League 2026/27 al 09/10/2026 (fonti: https://www.footballtransfers.com/en/transfer-news/uk-premier-league/2021/10/what-managers-have-been-sacked-this-season del 06/10/2026 e la pagina BBC "Manager ins and outs - 2026-27", in cui non compare nessun cambio di panchina di Premier fino al 10/10/2026): per la Premier non c'e' un caso da verificare, e' il risultato stesso.

| Lega | Squadra | Uscente | Entrante | Data | Allenatore nelle API | Fonte |
|---|---|---|---|---|---|---|
| Serie A | Fiorentina | Fabio Grosso | Paolo Vanoli | 2026-09-06 | da misurare | [fonte](https://sport.sky.it/calcio/serie-a/serie-a-2026-2027-allenatori-esonerati) |
| Serie A | Bologna | Domenico Tedesco | Raffaele Palladino | 2026-09-27 | da misurare | [fonte](https://sport.sky.it/calcio/serie-a/serie-a-2026-2027-allenatori-esonerati) |
| Serie A | Parma | Carlos Cuesta | Alberto Gilardino | 2026-09-27 | da misurare | [fonte](https://www.corrieredellosport.it/news/calcio/serie-a/parma/2026/09/29-151546958/parma_gilardino_il_nuovo_allenatore_ora_ufficiale) |
| Bundesliga | Borussia Mönchengladbach | Eugen Polanski | Alexander Blessin | 2026-09-22 | da misurare | [fonte](https://www.bundesliga.com/de/bundesliga/news/alexander-blessin-gladbach-trainer-fix-nachfolger-eugen-polanski-39297) |
| Ligue 1 | Lens | Dino Toppmöller | Yannick Cahuzac | 2026-09-15 | da misurare | [fonte](https://www.franceinfo.fr/sports/foot/rc-lens/ligue-1-yannick-cahuzac-restera-l-entraineur-de-lens-au-dela-du-match-a-monaco_8197349.html) |
| La Liga | Osasuna | Luis Miguel Ramis | Jagoba Arrasate | 2026-10-12 | da misurare | [fonte](https://www.infobae.com/america/agencias/2026/10/12/el-osasuna-espanol-destituye-a-su-entrenador-luis-miguel-ramis-y-jagoba-arrasate-vuelve/) |

Casi pubblici raccolti: **6** (la regola chiede almeno 3 casi e che TUTTI risultino aggiornati nel run reale).

## Cosa manca per misurare

**Il workflow manuale `audit_allenatori.yml`** (`workflow_dispatch`: lo lancia Felice, non questo referto). Fa, in quest'ordine:

1. i test offline della sonda (nessuna rete, nessuna chiave);
2. ~5 chiamate per l'elenco squadre delle 5 leghe + 1 chiamata per squadra (`GET /v4/competitions/{codice}/teams`, poi `GET /v4/teams/{id}`): ~100 squadre, ~11 minuti a 10 chiamate al minuto, il limite del piano gratuito;
3. scrive `audit/data/allenatori/<giorno>.json` **solo** se almeno una lega e' arrivata in fondo (almeno una chiamata riuscita) e riscrive **questo** referto con copertura, forme delle date e l'esito dei casi; se tutte le chiamate falliscono il workflow si ferma con errore e non committa nulla;
4. committa snapshot e referto con il token del bot.

Dopo quel run questo referto conterra' i numeri veri: la copertura per lega, la forma delle date di contratto cosi' come arrivano, l'allenatore che le API riportano per ogni caso pubblico e l'esito della regola. Solo allora si sapra' se l'allenatore puo' entrare nella scheda partita.

## Cosa NON fa questa sonda

* non modifica l'app ne' `SoccerMath/`: la scheda partita non mostra l'allenatore;
* non stampa la chiave API (header `X-Auth-Token`, mai nell'URL) e rifiuta di scrivere un file che la contenga;
* non scrive snapshot senza chiamate riuscite: nessun file con la data viene creato in modalita' «non eseguita».
