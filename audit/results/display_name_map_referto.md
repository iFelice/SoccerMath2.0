# DISPLAY_NAME_MAP: nomi solo-UI per la visualizzazione — referto

**Data esecuzione:** 2026-09-19 18:49 UTC
**Base di confronto:** `origin/main` (660ba488)
**Esito: VERDE** — cambio puramente cosmetico: stessi risultati, stesse probabilita', stesso Top Mix; cambia solo il nome mostrato.

> Ricostruzione del referto del 15/09 (`giornata_nomi_e_date_matchday6.md`, mai committato e non recuperabile da nessun branch/stash/PR): la tabella e le forme grezze sono state rimesurate dai dati presenti nel repository (righe raw dei `*_Live.csv` 2026/27, alias documentati in `TEAM_NAME_MAP`, `audit/results/schalke_bayern_921.json`).

## 1. Disegno

- `SoccerMath/display_names.py` (NUOVO): `DISPLAY_NAME_MAP` + `display_name()`, separato da `TEAM_NAME_MAP`/`UNDERSTAT_NAME_MAP` (invariati: servono al calcolo).
- Chiavi = nomi **canonici**: `display_name()` risolve qualunque forma grezza tramite `clean_name` (la stessa garanzia dei lookup del motore) ed e' quindi immune alla variante esatta che l'API restituisce.
- Fuori mappa: pass-through immutato (nessun fuzzy matching, nessun guess — comportamento pre-esistente).
- Applicato SOLO nei 4 punti di visualizzazione identificati dal referto (verificati invariati dal 15/09: `app.py` e' byte-identico fra la PR#23 e oggi):
  1. `get_ultimi_risultati_fd` — stringa ultimi risultati;
  2. `fetch_and_calc_top_mix` — righe ed etichette;
  3. `analisi_rapida_giornata` — etichette, pronostico e campi home/away del registro;
  4. card del tab PARTITE.
- I punti di confronto/chiave ricevono sempre il nome GREZZO: `team_stats.get(clean_name(...))`, `predict_elo_probs`, `blend_elo_into_1x2`, `show_details` (che fa matching contro live_data/classifica). Il grading del registro e le dedup sono per `match_id`/`(match_id, origin, selector_version)`: i nomi display non li toccano.

## 2. Tabella delle 96 squadre (2026/27, misurata)

Le "forme grezze" sono le varianti non canoniche osservate: righe raw nei `*_Live.csv` 2026/27 (scritte prima degli alias) e alias delle API live documentati in `TEAM_NAME_MAP`. "invariato" = la squadra non ha voce in mappa e l'UI continua a mostrare il nome grezzo dell'API, esattamente come prima del cambio.

| Lega | Canonico (chiave motore) | Forme grezze osservate | Display |
|---|---|---|---|
| Serie A | Atalanta | Atalanta BC | **invariato** |
| Serie A | Bologna | — | **invariato** |
| Serie A | Cagliari | Cagliari Calcio | **invariato** |
| Serie A | Como | — | **invariato** |
| Serie A | Fiorentina | ACF Fiorentina | **invariato** |
| Serie A | Frosinone | — | **invariato** |
| Serie A | Genoa | Genoa CFC | **invariato** |
| Serie A | Inter | FC Internazionale Milano, Inter Milan | **invariato** |
| Serie A | Juventus | Juventus FC | **invariato** |
| Serie A | Lazio | SS Lazio | **invariato** |
| Serie A | Lecce | — | **invariato** |
| Serie A | Milan | AC Milan | **invariato** |
| Serie A | Monza | — | **invariato** |
| Serie A | Napoli | SSC Napoli | **invariato** |
| Serie A | Parma | Parma Calcio 1913 | **invariato** |
| Serie A | Roma | AS Roma | **invariato** |
| Serie A | Sassuolo | — | **invariato** |
| Serie A | Torino | — | **invariato** |
| Serie A | Udinese | Udinese Calcio | **invariato** |
| Serie A | Venezia | — | **invariato** |
| Premier League | Arsenal | — | **invariato** |
| Premier League | Aston Villa | — | **invariato** |
| Premier League | Bournemouth | AFC Bournemouth | **invariato** |
| Premier League | Brentford | — | **invariato** |
| Premier League | Brighton | Brighton Hove, Brighton and Hove Albion | **Brighton** |
| Premier League | Chelsea | — | **invariato** |
| Premier League | Coventry City | — | **invariato** |
| Premier League | Crystal Palace | — | **invariato** |
| Premier League | Everton | — | **invariato** |
| Premier League | Fulham | — | **invariato** |
| Premier League | Hull City | — | **invariato** |
| Premier League | Ipswich | Ipswich Town | **invariato** |
| Premier League | Leeds | Leeds United | **invariato** |
| Premier League | Liverpool | — | **invariato** |
| Premier League | Man City | Manchester City | **invariato** |
| Premier League | Man United | Manchester United | **invariato** |
| Premier League | Newcastle | Newcastle United | **invariato** |
| Premier League | Nott'm Forest | Nottingham, Nottingham Forest | **Nottingham Forest** |
| Premier League | Sunderland | — | **invariato** |
| Premier League | Tottenham | Tottenham Hotspur | **invariato** |
| La Liga | Alaves | Alavés, Deportivo Alaves | **invariato** |
| La Liga | Ath Bilbao | Athletic, Athletic Bilbao | **Athletic Bilbao** |
| La Liga | Ath Madrid | Atleti | **Atletico Madrid** |
| La Liga | Barcelona | Barça | **Barcelona** |
| La Liga | Betis | Real Betis | **invariato** |
| La Liga | Celta | — | **invariato** |
| La Liga | Deportivo | — | **invariato** |
| La Liga | Elche | — | **invariato** |
| La Liga | Espanol | Espanyol | **invariato** |
| La Liga | Getafe | — | **invariato** |
| La Liga | Levante | — | **invariato** |
| La Liga | Málaga | — | **invariato** |
| La Liga | Osasuna | — | **invariato** |
| La Liga | Real Madrid | — | **invariato** |
| La Liga | Santander | — | **Racing Santander** |
| La Liga | Sevilla | — | **invariato** |
| La Liga | Sociedad | Real Sociedad | **invariato** |
| La Liga | Valencia | — | **invariato** |
| La Liga | Vallecano | Rayo Vallecano | **invariato** |
| La Liga | Villarreal | — | **invariato** |
| Bundesliga | Augsburg | FC Augsburg | **invariato** |
| Bundesliga | Bayern | Bayern Munich | **invariato** |
| Bundesliga | Dortmund | Borussia Dortmund | **invariato** |
| Bundesliga | Ein Frankfurt | Eintracht Frankfurt, Frankfurt | **Eintracht Frankfurt** |
| Bundesliga | Elversberg | — | **invariato** |
| Bundesliga | Freiburg | SC Freiburg | **invariato** |
| Bundesliga | Hamburg | HSV | **Hamburg** |
| Bundesliga | Hoffenheim | TSG Hoffenheim | **invariato** |
| Bundesliga | Koln | Köln | **invariato** |
| Bundesliga | Leipzig | RB Leipzig | **invariato** |
| Bundesliga | Leverkusen | Bayer 04 Leverkusen | **invariato** |
| Bundesliga | M'gladbach | Borussia Mönchengladbach | **Borussia Mönchengladbach** |
| Bundesliga | Mainz | 1. FSV Mainz 05 | **invariato** |
| Bundesliga | SC Paderborn | — | **invariato** |
| Bundesliga | Schalke 04 | Schalke | **Schalke 04** |
| Bundesliga | Stuttgart | VfB Stuttgart | **invariato** |
| Bundesliga | Union Berlin | — | **invariato** |
| Bundesliga | Werder Bremen | Bremen, SV Werder Bremen | **Werder Bremen** |
| Ligue 1 | Angers | Angers SCO | **invariato** |
| Ligue 1 | Auxerre | AJ Auxerre | **invariato** |
| Ligue 1 | Brest | Stade Brestois 29 | **invariato** |
| Ligue 1 | Le Havre | Le Havre AC | **invariato** |
| Ligue 1 | Le Mans | — | **invariato** |
| Ligue 1 | Lens | RC Lens | **invariato** |
| Ligue 1 | Lille | — | **invariato** |
| Ligue 1 | Lorient | — | **invariato** |
| Ligue 1 | Lyon | Olympique Lyon, Olympique Lyonnais | **Lyon** |
| Ligue 1 | Marseille | Olympique de Marseille | **invariato** |
| Ligue 1 | Monaco | — | **invariato** |
| Ligue 1 | Nice | OGC Nice | **invariato** |
| Ligue 1 | PSG | Paris SG, Paris Saint-Germain | **invariato** |
| Ligue 1 | Paris | — | **Paris FC** |
| Ligue 1 | Rennes | Stade Rennais, Stade Rennais FC | **Rennes** |
| Ligue 1 | Strasbourg | RC Strasbourg Alsace | **invariato** |
| Ligue 1 | Toulouse | Toulouse FC | **invariato** |
| Ligue 1 | Troyes | — | **invariato** |

Totale squadre: **96** (20 Serie A + 20 Premier + 20 La Liga + 18 Bundesliga + 18 Ligue 1). La Serie A non ha voci in mappa: i 20 shortName 2026/27 sono gia' nomi completi.

## 3. Equivalenza PRE/POST sui flussi reali

### fetch_and_calc_top_mix (funzione PRE eseguita dal sorgente git della base, funzione POST dal codice attuale, stessi fixture)

- righe PRE: 8, righe POST: 8; leghe mancanti PRE=[] POST=[]
- campi identici al bit: `league`, `giornata`, `match_id`, `utcDate`, `rank`, `prob`, `prob_val`, `poisson`, `elo`, `elo_disponibile`, **`mercato_standard`**
- campi che cambiano (e come atteso): `home`, `away`, `market` (solo sostituzione del nome)
- errori: **0**

Esempi (PRE → POST):

- `Real Madrid vs Málaga` [Vittoria Real Madrid / 1 / 85.8%] → `Real Madrid vs Málaga` [Vittoria Real Madrid / 1 / 85.8%]
- `Köln vs Bayern` [Vittoria Bayern / 2 / 83.6%] → `Köln vs Bayern` [Vittoria Bayern / 2 / 83.6%]
- `Brighton Hove vs Nottingham` [GG / GG / 63.4%] → `Brighton vs Nottingham Forest` [GG / GG / 63.4%]
- `Atleti vs Barça` [GG / GG / 63.0%] → `Atletico Madrid vs Barcelona` [GG / GG / 63.0%]

### analisi_rapida_giornata

- salvataggi PRE: 2, POST: 2
- identici: `prob`, `prob_poisson`, `mercato_standard`, `origin`, `giornata`
- cambiano (come atteso): `home`, `away`, `pron` (solo sostituzione del nome)
- errori: **0**

## 4. Guardie strutturali

- file modificati verso origin/main: SoccerMath/app.py, SoccerMath/test_topmix_selector_parity.py
- `team_aliases.py`, `config.py`, `models/elo_engine.py`, `prediction_registry.py`, `team_names.py`, `update_db.py`: **invariati**
- il layer display non e' importato da nessun modulo di calcolo
- chiamate `display_name(` in `app.py`: 8 (2 ultimi risultati + 2 Top Mix + 2 Analisi Rapida + 2 card)
- `test_topmix_selector_parity.py`: il test esegue il testo CORRENTE di `fetch_and_calc_top_mix` in un namespace di stub; il solo aggiustamento e' iniettarvi la `display_name` VERA (i nomi sintetici della griglia non hanno voci in mappa, quindi e' pass-through identita' e la parita' bit-per-bit col fixture PRE-refactor resta pienamente significativa: 26/26 verdi).
- errori: **0**

## 5. Render end-to-end (app vera, Streamlit AppTest, API mockate)

- **Serie A**: Inter→Inter (OK); Milan→Milan (OK); Napoli→Napoli (OK); Juventus→Juventus (OK)
- **Premier League**: Brighton Hove→Brighton (OK); Nottingham→Nottingham Forest (OK); Man City→Man City (OK); Leeds United→Leeds United (OK)
- **La Liga**: Atleti→Atletico Madrid (OK); Barça→Barcelona (OK); Athletic→Athletic Bilbao (OK); Santander→Racing Santander (OK); Real Madrid→Real Madrid (OK); Málaga→Málaga (OK)
- **Bundesliga**: HSV→Hamburg (OK); Schalke→Schalke 04 (OK); Frankfurt→Eintracht Frankfurt (OK); M'gladbach→Borussia Mönchengladbach (OK); Köln→Köln (OK); Bayern→Bayern (OK)
- **Ligue 1**: Stade Rennais→Rennes (OK); Olympique Lyon→Lyon (OK); Paris→Paris FC (OK); PSG→PSG (OK)
- Tab TOP MIX: 8 righe renderizzate; nessuna forma grezza mappata visibile
- errori: **0**

## 6. Come riprodurre

```bash
python3 audit/display_name_map_check.py --base origin/main
```
Suite completa: `pytest SoccerMath/ audit/ --ignore=SoccerMath/test_theme_toggle.py` (attesi i 2 fallimenti pre-esistenti su main, estranei a questo cambio).
