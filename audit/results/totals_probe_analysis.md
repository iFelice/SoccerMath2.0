# Sonda The Odds API — mercato totals (audit, offline)

Generato da `audit/totals_probe_analysis.py` il 2026-10-10T15:32:22Z a partire da 0 snapshot in `audit/data/totals_probe/`. Nessuna chiamata di rete, nessuna chiave.

## 1. Crediti spesi

| lega (sport_key) | x-requests-last (crediti della chiamata) |
|---|---|

**Crediti spesi: 0.** Ultimo stato del conto: used=None, remaining=None.

## 2. Eventi e Pinnacle

| lega | file | status | eventi |
|---|---|---|---|

- Eventi totali: **0**.
- Eventi con **Pinnacle** sul mercato totals: **0**.

## 3. Linee per bookmaker (una linea per libro e per evento)

Nessuna linea totals nei file.

## 4. Eventi con linea 2,5 e linee asiatiche

| misura | eventi |
|---|---|
| con una linea 2,5 da almeno un bookmaker | 0 |
| con una linea 2,5 da Pinnacle | 0 |
| con SOLO linee asiatiche (2,25 / 2,75), nessuna 2,5 | 0 |
| con almeno una linea asiatica (candidati alla sensibilita') | 0 |

## 5. Trattamento delle linee asiatiche

Decisione dichiarata in `audit/totals_probe_analysis.py` (prima dei dati): **esclusione** nel confronto principale; la conversione e' solo sensibilita', non implementata. Motivo: una linea 2,25/2,75 e' una combinazione di mezze puntate su linee vicine con rimborso parziale. Per convertirla in P(Over 2,5) bisogna assumere come il libro prezza le due meta': non e' un dato osservato.

**Esito: sonda NON ESEGUITA o senza eventi.** Il workflow `totals_probe.yml` non ha ancora prodotto snapshot con eventi. Nessun numero di questo referto e' un risultato.

## 6. Limiti

- Una linea per libro e per evento: se un libro offre piu' linee nello stesso evento se ne tiene la piu' bassa.
- La sonda misura la DISPONIBILITA' delle linee, non le quote Over/Under: le quote sono nel corpo grezzo e non vengono usate qui.
- L'ora della rilevazione e' quella della chiamata (`fetched_at_utc`), non l'ora di chiusura del mercato.
