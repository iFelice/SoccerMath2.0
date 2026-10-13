# Sonda assenze — referto di audit

## Regola decisionale (prima dei numeri)

1. **Squalifiche**: fa fede solo il provvedimento ufficiale del Giudice Sportivo (Serie A), della RFEF (La Liga) o della Commissione LFP (Ligue 1). I cartellini non sono mai usati per ricostruire una squalifica già pronunciata.
2. **Serie A — diffidati**: soglie progressive 5, 9, 13, 16, 18 e ogni ammonizione dalla 19ª. È diffidato chi ha un progressivo per cui la prossima ammonizione raggiunge una soglia. La lista è completa soltanto con tutti i comunicati ufficiali dalla 1ª giornata; altrimenti è `non calcolabile`, non zero.
3. **Fonte non ufficiale**: può essere dichiarata affidabile per le squalifiche solo dopo concordanza esatta di tutti i calciatori con la fonte ufficiale per **due giornate consecutive** in una lega coperta da fonte ufficiale. Solo dopo tale verifica può coprire Premier League/Bundesliga dove necessario. Una fonte esclusa dai termini non viene confrontata e non accumula giornate di affidabilità.
4. **Errore di fonte** (documento non trovato, HTTP diverso da 200, zero righe o schema cambiato) = **non letta**, con motivo. Non significa mai «nessuno squalificato».
5. **Infortuni/formazioni**: non sono raccolti da questa sonda. Ogni eventuale dato manuale deve sempre riportare fonte, URL e ora di aggiornamento/raccolta.

## Esecuzione

- Nessun run di `audit_assenze.yml` registrato in questo referto iniziale.

### Diagnostica per fonte

| Fonte | Stato | HTTP per richiesta (byte) | Byte totali | Documento trovato | Righe estratte | Squadre non abbinate |
|---|---|---|---:|---|---:|---|
| Giudice Sportivo — Serie A | non letta (job senza esito; snapshot assente) | n/d (nessuna richiesta) | 0 | no | 0 | n/d |
| RFEF — Primera División / La Liga | non letta (job senza esito; snapshot assente) | n/d (nessuna richiesta) | 0 | no | 0 | n/d |
| LFP — Ligue 1 | non letta (job senza esito; snapshot assente) | n/d (nessuna richiesta) | 0 | no | 0 | n/d |
| RotoWire | non letta (job senza esito; snapshot assente) | n/d (nessuna richiesta) | 0 | no | 0 | n/d |
| Premier Injuries | non letta (job senza esito; snapshot assente) | n/d (nessuna richiesta) | 0 | no | 0 | n/d |
| Fantacalcio.it | non letta (job senza esito; snapshot assente) | n/d (nessuna richiesta) | 0 | no | 0 | n/d |

Nessuna richiesta o estrazione è stata eseguita nel referto iniziale; tutte le diagnostiche sono `n/d`.

## Confronto fonti non ufficiali

| Fonte richiesta | Stato | Verifica contro l'ufficiale |
|---|---|---|
| RotoWire | esclusa dai termini | non eseguita; concordanza 0/2 turni verificati |
| Premier Injuries | esclusa dall'archiviazione in rete senza autorizzazione scritta | non eseguita; concordanza 0/2 turni verificati |
| Fantacalcio.it | esclusa finché non esiste autorizzazione scritta ed espressa | non eseguita; concordanza 0/2 turni verificati |

Il numero `0/2` indica **nessun turno verificato**, non una discordanza né una fonte senza assenti. Non sono stati effettuati fetch automatici di queste fonti.

## Fonti ufficiali e termini d'uso controllati il 13/10/2026

| Fonte | Esito dei termini | Riferimento |
|---|---|---|
| Serie A / Lega Serie A | §2.4 limita l'uso a fini personali/non commerciali; §5.2 vieta estrazione/uso di contenuti, inclusi data-mining e robot, senza consenso scritto espresso. Attiva solo con autorizzazione scritta specifica. | [termini](https://www.legaseriea.it/terms-and-conditions) |
| La Liga / RFEF | Legal notice §2: vieta la riproduzione completa o parziale senza autorizzazione RFEF. Il dispatch richiede conferma dell'autorizzazione scritta. | [termini](https://rfef.es/en/legal-notice) |
| Ligue 1 / LFP | CGU §§6, 10: uso di consultazione personale entro la funzione prevista; le informazioni non possono essere riprodotte o riutilizzate senza consenso scritto preventivo. | [termini](https://ligue1.com/en/legal/cgu) |
| RotoWire | Esclusa: Article VI vieta mezzi automatici/scraping; Article VII limita l'uso tramite AI. | [termini](https://www.rotowire.com/termsandconditions.php) |
| Premier Injuries | Esclusa dagli snapshot GitHub: archivio personale ammesso su dispositivo locale, non su server/dispositivi di rete. | [termini](https://www.premierinjuries.com/terms) |
| Fantacalcio.it | Esclusa: NAVIGAZIONE §3 vieta software o meccanismi automatici/manuali di accesso/copia, compreso scraping, senza autorizzazione scritta ed espressa; vieta anche riuso/elaborazione dei contenuti. | [termini](https://www.fantacalcio.it/termini-e-condizioni) |

Le tre fonti ufficiali richiedono autorizzazione scritta per l'estrazione/riuso descritti dai rispettivi termini. L'operatore ha dichiarato il 13/10/2026 di possedere permessi scritti per Serie A, RFEF e LFP; i documenti di autorizzazione non sono conservati nel repository. Ogni job ufficiale è **fail-closed**: input di conferma per fonte predefinito `no`, nessuna richiesta se non impostato su `yes`.

## Verifica di formato su documenti reali

- **Serie A**: il PDF ufficiale CU n. 47 del 13/10/2026 (6ª giornata) è stato letto durante la verifica preliminare: 3 squalifiche di calciatori e 3 di allenatori, oltre alle ammonizioni progressive. Il fixture PDF dichiarato dall'utente non è nel checkout; il test del parser su quel PDF reale resta da eseguire quando sarà ripristinato. Il codice non crea una copia sostitutiva.
- **La Liga/RFEF**: PDF J7, comunicato 23/09/2026, verificato su documento reale; fixture testuale ridotto in `audit/fixtures/assenze/`. Tre squalifiche di calciatori: doppia ammonizione (1) e due espulsioni dirette (1 ciascuna). Il percorso ipotizzato per J8 restituiva 404 al 13/10; non si presume un URL per le giornate successive.
- **Ligue 1/LFP**: articolo disciplinare del 23/09/2026 (pubblicato 24/09), verificato su pagina reale; fixture testuale ridotto in `audit/fixtures/assenze/`. Quattro nominativi: una sanzione di 2 gare ferme + 2 con sursis, una da 1 gara e due da 1 gara per quinto avvertimento. È l'ultimo comunicato individuato nella ricerca del 13/10, non una garanzia che non ne esistessero di più recenti.
- I fixture La Liga/LFP sono estratti testuali minimi per test offline, non copie integrali dei PDF/HTML. I permessi scritti sono stati dichiarati dall'operatore; il repository non include i documenti di autorizzazione.

## Premier League e Bundesliga: fonti ufficiali trovate

- **Premier League**: la pagina ufficiale aggiornata al 12/10/2026 pubblica sospesi per GW7 e giocatori vicini alla soglia gialla; rimanda alle regole FA sulle soglie (5 entro le prime 19 gare; 10 entro la 32ª). La tabella non specifica il motivo disciplinare per ogni nominativo: la copertura è utile ma non completa per distinguere gialli/rossi senza ulteriore conferma. [Pagina ufficiale](https://www.premierleague.com/en/news/4425344/which-players-are-suspended-or-close-to-a-ban-in-fantasy).
- **Bundesliga**: il DFB mantiene una tabella ufficiale «Die aktuellen Sperren in der Bundesliga» con giocatore, club, decisione e motivo, aggiornata al 21/09/2026 alla consultazione; non è un calendario per giornata e in quel momento non mostrava una squalifica per accumulo gialli. [Tabella DFB](https://www.dfb.de/ueber-uns/verbandsrecht/sperren). La pagina redazionale Bundesliga.com consultata è indicata «correct as of 14 September 2026» e non migliora l'aggiornamento per il 13/10. Nessuna delle due fonti è stata automatizzata; termini d'uso per eventuale lettore da verificare prima del codice.

## Modalità di lancio e lacune operative

- Solo `workflow_dispatch`; un job indipendente per fonte; un URL ufficiale diretto per ogni documento; nessun crawling dell'indice e nessun URL RFEF futuro indovinato.
- Inserire la finestra (es. `16–19/10/2026`, `23–26/10/2026` oppure `confronto dopo comunicato del martedì`), i PDF/URL ufficiali esatti e confermare separatamente i permessi scritti per ogni fonte. Il lettore effettua una richiesta per pagina, con User-Agent identificativo e pausa di 3 secondi; redirect e retry sono disabilitati.
- Per diffidati Serie A completi, fornire nell'input tutti i PDF precedenti dalla 1ª giornata e confermare che l'archivio non omette documenti/parti. Con un solo PDF la lista resta parziale.
- Squadre abbinate con `team_aliases.clean_name`, crosswalk ufficiale dichiarato e `display_names.display_name`; nessun fuzzy matching. Ogni nome non abbinato resta visibile in tabella.
- Non è stata lanciata alcuna acquisizione reale in questa PR. I job, il referto e i test non modificano `SoccerMath/` né l'app.
