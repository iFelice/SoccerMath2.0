# Prova all'indietro delle squalifiche — 2025/26 e 2026/27

**Stato: regola dichiarata, NUMERI NON MISURATI.** Questo referto non contiene
richiamo, precisione o conteggi: non sono stati calcolati. Motivi e cosa serve
sono nelle sezioni in fondo.

Data di redazione: 2026-10-13. Motore: `audit/squalifiche_feasibility.py` (PR #33),
non modificato.

## Regola dichiarata (scritta prima di qualunque numero)

1. **Cosa si prova.** Per ogni lega L e giornata N, con il motore PR #33 si
   produce la lista prevista di squalifiche per la giornata N usando **solo i dati
   con kickoff prima dell'inizio della giornata N** (archivio `player_match` e xG).
   Il calendario completo è noto in anticipo, quindi la partita saltata è quella
   successiva della squadra anche se non ancora giocata.
2. **Giornate.** L'archivio partite non ha il campo giornata. La giornata viene
   ricostruita dalle date: partite in ordine di kickoff, ogni partita va nella prima
   giornata in cui nessuna delle due squadre ha già giocato. È un'approssimazione:
   rinvii e recuperi possono spostarla. Va dichiarata in ogni tabella.
3. **Verità di riferimento.** Il comunicato ufficiale del Giudice Sportivo della
   giornata N. Serie A: Lega Serie A. Altre leghe: fonte ufficiale, o un sostituto
   pubblico dichiarato con fonte e data (da scegliere prima di misurare).
4. **Cause separate:** (a) accumulo di ammonizioni; (b) doppia ammonizione;
   (c) rosso diretto.
5. **Metriche per lega e per causa:**
   - richiamo = squalifiche ufficiali previste / squalifiche ufficiali;
   - precisione = squalifiche ufficiali previste / squalifiche previste;
   - conteggi: previste, ufficiali, in comune, solo previste, solo ufficiali.
6. **Soglia per la scheda partita (decisa su 2025/26):** una lega entra in scheda
   per le squalifiche da **accumulo** e da **doppia ammonizione** solo se, per
   **ciascuna** delle due cause, richiamo ≥ 95% **e** precisione ≥ 95%.
7. **Rossi diretti:** se la lega entra, un rosso diretto si mostra **solo** come
   «squalificato almeno per 1 giornata». Nessun'altra soglia per i rossi.
8. **Leghe che non passano** restano fuori dalla scheda partita.
9. **2026/27 (giornate 2–7)** è un controllo fuori campione: non serve a decidere
   la soglia, e viene riportato separatamente.

## Limiti del motore già noti dal codice (non misurati)

- **Doppia ammonizione non prevista.** Le righe giocatore con giallo e rosso nella
  stessa partita vanno in `ambiguous` e non generano evento (`reconstruct_events`).
  Con la regola sopra, finché il motore non cambia, nessuna lega può passare sulla
  doppia ammonizione: il risultato atteso è **nessuna lega in scheda**. Non
  modifico il motore in questo lavoro: sarebbe un'altra PR.
- Il motore dichiara già la propria precisione come «NON VERIFICABILE (ground truth
  ufficiale non versionata)»: è esattamente la verità di riferimento che questa
  prova deve costruire.
- **Ligue 1 2024/25**: solo campionato (coppe nazionali mancanti, dichiarato dal motore).
- **La Liga**: quinta ammonizione all'ultima giornata esclusa (esenzione, art. 112.4).
- **Serie A**: soglie di accumulo `[5, 9, 13, 16, 18]` e poi ogni ammonizione da 19.
  Sono quelle del motore: non verificate in questo lavoro.

## Stato delle giornate 2026/27 (dai `*_Live.csv`)

Al 12/10/2026 la Serie A ha 60 partite giocate: **6 giornate complete** su 38. Quindi
la giornata **7 di Serie A non è ancora stata giocata**: non esiste un comunicato
ufficiale da confrontare, e N=7 per la Serie A non è valutabile finché non si gioca.
Per le altre leghe il conto va fatto con lo stesso criterio (partite giocate / squadre
÷ 2) prima di misurare.

## Fonti ufficiali trovate da questa sandbox

- `https://www.legaseriea.it/giudice-sportivo`: pagina **404** (URL non più valido).
- Lega Serie A, «Le decisioni del Giudice Sportivo» per la **6ª giornata di Serie A
  Enilive 2026/2027**, pubblicata il 13/10/2026, con il comunicato ufficiale in
  allegato ([1](https://www.legaseriea.it/serie-a/news/le-decisioni-del-giudice-sportivo-x9431)).
  Dal testo della notizia risultano squalificati per un turno Elmas (Atalanta),
  Lucchesi (Monza) e Malen (Roma), e gli allenatori Pisacane (Cagliari) e Spalletti
  (Juventus). **Il comunicato allegato non è stato letto**: questo è solo il riassunto
  della notizia, quindi non è ancora una verità di riferimento.
- Comunicati 2025/26 (38 giornate × 5 leghe) e giornate 2–6 del 2026/27: **non
  raccolti**. Non sono un controllo che si possa fare a campione in questa sandbox.

## Perché non ci sono numeri

1. **Archivio `player_match` non disponibile qui.** L'artifact è su
   `*.blob.core.windows.net`, host non raggiungibile dalla sandbox. Lo stesso archivio
   serve al referto `sonda_squalifiche.md`: run sorgente **38404660658**, artifact
   `ppda-player-verify-38404660658` (id 11820168530), **scade il 2026-10-27T14:04:31Z**.
2. **Liste ufficiali non raccolte** (vedi sopra).
3. **Harness non scritto.** Non posso validarlo su dati reali da qui. Il codice va
   scritto e testato insieme al primo run con archivio.

## Cosa serve per misurarla (lanci da Felice)

- **Prima del 27/10/2026:** lanciare `audit_squalifiche.yml` (workflow_dispatch) con
  input `run_id` = `38404660658`. Scarica l'archivio e riscrive
  `audit/results/sonda_squalifiche.md`. Lo stesso archivio serve alla prova.
- **Dopo il 27/10/2026:** prima rilanciare `ppda_player_verify.yml` (workflow_dispatch,
  circa 40 minuti), poi `audit_squalifiche.yml` con il nuovo `run_id`.
- **Liste ufficiali:** Felice decide se fornire i file
  `audit/data/squalifiche/ufficiali/<lega>_<stagione>_g<N>.json` (una giornata per
  file, con fonte e data di pubblicazione) oppure se autorizzare la raccolta dai
  comunicati pubblici. Senza questi file la prova non si può fare.
