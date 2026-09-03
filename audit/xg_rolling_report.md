# Audit — xG per partita e versione rolling (media ultime 5) per il fix Elo: dati NON disponibili

**Stato: STOP — nessuno script eseguito, nessuna metrica prodotta.**
Solo questo report. Non sono stati inventati dati, non è stata costruita alcuna
versione rolling.

Data: 2026-09-01 · Branch: `arena/01a052d7-soccermath2-0` (PR #7)

---

## 1. Esito della verifica

**La fonte attuale NON fornisce xG per partita.** Il meccanismo `update_xg.py` →
`scraper_xg.py` → `database/xg_*.json`, che è l'unico punto da cui l'Elo legge
gli xG, espone solo la **media stagionale per squadra** (`xG_avg`, `xGA_avg`).
Non c'è quindi alcuna base per calcolare una media mobile su "ultime 5 partite",
che per definizione richiede lo storico partita-per-partita.

Ai sensi della consegna ("Se i dati per xG per-partita NON sono disponibili
nella fonte attuale, fermati e scrivi solo un report che lo spiega"), il task
si arresta qui.

---

## 2. Evidenze verificate sul codice/dati reali

### 2.1 Cosa salva la fonte (solo medie stagionali)
- `SoccerMath/update_xg.py` righe 99–109: legge `history` da Understat ma la
  riduce subito a due numeri per squadra —
  `total_xg = sum(m.get("xG",0))`, `xGA = sum(m.get("xGA",0))`,
  `xG_avg = total_xg / matches_played`, `xGA_avg = ...`.
  Il dettaglio partita-per-partita viene **scartato**.
- riga 127: salva il JSON con `json.dump(data, ...)` dove `data` è solo
  `{squadra: {xG_avg, xGA_avg}}`.
- `SoccerMath/scraper_xg.py` riga 4 (docstring): *"get_understat_xg →
  {nome: {xG_avg, xGA_avg}}"*; righe 22–30: legge i file JSON e li ritorna
  così come sono. Nessun campo `history`/`matches`/`date` nel payload.

### 2.2 Contenuto effettivo dei file `xg_data` (verificato)
`SoccerMath/database/xg_serie_a.json`, `xg_premier_league.json`,
`xg_la_liga.json`, `xg_bundesliga.json`, `xg_ligue_1.json` — ogni entry è
esattamente del tipo:

```json
"Atalanta": { "xG_avg": 1.61, "xGA_avg": 1.04 }
```

Non esiste alcuna lista di partite, né date, né per-match xG/xGA. Non esiste
nemmeno una colonna xG nei CSV delle partite (`database/*.csv`, fonte
football-data.co.uk): verificato su `SerieA_2025.csv`, `Premier_2024.csv`,
`Bundesliga_2022.csv`, `SerieA_Live.csv` (nessuna colonna contenente xG).

### 2.3 Punto d'ingresso dell'Elo
- `SoccerMath/models/elo_engine.py` riga 22 e 92: `get_understat_xg(...)`.
- righe 126–135 (il "xG-fix" in produzione, non toccato):
  ```
  h_xg  = xg_data[h_team].get("xG_avg", 1.3)
  h_xga = xg_data[h_team].get("xGA_avg", 1.3)
  a_xg  = xg_data[a_team].get("xG_avg", 1.3)
  a_xga = xg_data[a_team].get("xGA_avg", 1.3)
  xg_adj = ((h_xg - h_xga) - (a_xg - a_xga)) * 0.15
  xg_elo_boost = max(-100, min(100, xg_adj * 400))
  dr = r_h + home_adv - r_a + xg_elo_boost
  ```
  Sostituire `xG_avg`/`xGA_avg` con la media delle ultime 5 partite richiede di
  avere, per ogni partita, lo storico xG/xGA delle precedenti partite della
  squadra — dato assente.

---

## 3. Perché non è ottenibile nemmeno ri-scraping (in questo ambiente)

Anche se `update_xg.py` *vede* lo storico partita-per-partita dentro il campo
`history` di Understat nel momento in cui fa lo scraping, tre ostacoli rendono
il dato di fatto non disponibile qui:

1. **Nessun accesso di rete.** Nell'ambiente di lavoro ogni richiesta HTTPS
   fallisce (`SSLZeroReturnError`/TLS EOF) — testato verso
   `understat.com`, `google.com`, `example.com`. Non è possibile eseguire
   `update_xg.py` né alcun fetch verso Understat.
2. **Lo scraper esistente non lo salva.** Anche riuscendo a fare scraping,
   `update_xg.py` riduce `history` a media stagionale e la persiste senza
   partite; per ottenere per-partita bisognerebbe modificare lo scraper
   (cambio del formato dati `database/xg_*.json`), lavoro sullo strato dati
   fuori dallo scopo del task e che non produrrebbe comunque i dati ora.
3. **Copertura stagionale insufficiente.** Lo split richiesto (validation
   2024/25 + test 2025/26) richiede per-partita per le stagioni storiche
   2024/25 e 2025/26. Lo scraper è configurato per la sola stagione corrente
   (`LEAGUES` in `update_xg.py` → `season: 2026`), quindi non fornirebbe lo
   storico necessario alle due stagioni oggetto della verifica.

---

## 4. Conclusione e azione richiesta per sbloccare

Il task di confronto **rolling-xG (ultime 5) vs xG stagionale** non può essere
eseguito con la fonte attuale: manca il dato per-partita, e non è lecito
ricostruirlo/inderlo (vincolo esplicito della consegna).

Per sbloccarlo serve un prerequisito sullo strato dati, da pianificare come
task separato (come già anticipato al punto 9 del piano in
`soccermath_probability_review.md`):

- estendere `update_xg.py` per **persistere lo storico partita-per-partita**
  (campo `history` di Understat: per ogni partita data, avversario, `xG`,
  `xGA`, `h_a`), senza rompere l'interfaccia `get_understat_xg` esistente
  (aggiungere un campo/endpoint in parallelo, e.g. `get_understat_xg_history`);
- eseguire lo scraping in un ambiente con accesso a rete verso Understat, per
  le stagioni 2024/25 e 2025/26 (oltre alla corrente);
- solo a quel punto costruire in `audit/` la media mobile "ultime 5 partite"
  (con no-leakage: media calcolata esclusivamente sulle partite antecedenti
  quella corrente, in ordine cronologico) e replicare il confronto Elo
  rolling vs stagionale su validation/test, 5 leghe, con Brier/LogLoss/ROI
  (vs B365) su 1X2 ed ensemble, come da consegna.

Nessuna di queste condizioni è soddisfatta oggi → **STOP, report only.**
