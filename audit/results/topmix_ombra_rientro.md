# Regola di rientro dei Totali nel Top Mix (registro ombra)

Generato: `2026-10-08T19:37:37Z` - sola lettura, nessuna scrittura nel registro.

**Sorgente:** upstash non raggiungibile: RegistryStoreError: registro ombra: richiede REGISTRY_BACKEND=upstash (attuale: jsonbin)  
**Stato della lettura:** NON VERIFICABILE

## Esito

**NON VERIFICABILE: registro ombra non letto dalla sorgente richiesta. Nessun conteggio e' stato fatto: zero non significa 'nessuna scelta'.**

## Costanti (fissate prima dei dati)

| costante | valore |
|---|---|
| mercati che possono rientrare | OVER_2.5, UNDER_2.5 (solo O/U 2.5) |
| GG/NG | fuori_definitivamente (registrati in ombra, mai rientrano) |
| campione fuori campione | stagione 2026/2027 in poi |
| N minimo (scelte O/U ammesse giudicate) | 300 |
| (a) margine calibrazione | hit - confidenza media >= -2 pp, IC include 0 o sta sopra |
| (b) margine base rate | hit - base rate O/U >= +5 pp, IC esclude 0 |
| IC | 95% percentile, bootstrap a blocchi lega-giornata-stagione |
| repliche / seme | 2000 / 20261008 |
| base rate O/U | stagioni 2022/2023, 2023/2024, 2024/2025, 2025/2026 dai CSV del repo (esclusa la stagione in corso) |

## Base rate Over 2.5 (riferimento, per lega)

| lega | partite | Over 2.5 | tasso |
|---|---:|---:|---:|
| Bundesliga | 1224 | 754 | 61.6% |
| La Liga | 1520 | 731 | 48.1% |
| Ligue 1 | 1298 | 707 | 54.5% |
| Premier League | 1520 | 870 | 57.2% |
| Serie A | 1520 | 717 | 47.2% |

## Campione

Nessun dato letto: la sorgente non era raggiungibile (vedi stato).

## Criteri

Criteri non calcolati: nessun dato letto.

_Lettura della regola: vedi docstring di `audit/topmix_ombra_rientro.py`. Il rientro richiede N sufficiente e (a) e (b) insieme._
