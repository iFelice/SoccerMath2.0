# Sonda assenze — solo audit

Questi moduli non sono importati dall'app e non modificano `SoccerMath/`. La sonda legge soltanto documenti ufficiali **quando la persona che lancia il workflow conferma il relativo permesso scritto**. Non stima indisponibilità e non trasforma errori di lettura in liste vuote.

## Fonti e limiti di autorizzazione

La revisione dei termini del 13/10/2026 è registrata in `audit/results/sonda_assenze.md`:

- Serie A: i termini Lega Serie A §5.2 citano espressamente data-mining/robot e richiedono consenso scritto per estrazione/uso. Il job resta fermo senza input `authorize_serie_a=yes`.
- La Liga: il legal notice RFEF vieta riproduzione completa o parziale senza autorizzazione. Il job resta fermo senza `authorize_rfef=yes`.
- Ligue 1: le CGU LFP limitano l'uso alla consultazione personale prevista e vietano il riuso/riproduzione delle informazioni senza consenso scritto. Il job resta fermo senza `authorize_lfp=yes`.
- RotoWire, Premier Injuries e Fantacalcio.it: esclusi, senza richieste HTTP. I relativi job producono solo uno snapshot di esclusione dai termini.

L'operatore ha dichiarato di possedere permessi scritti per le tre fonti ufficiali il 13/10/2026. Le autorizzazioni non sono archiviate nel repository. Prima di ogni run vanno verificati validità, titolare e ambito: l'input `yes` deve coprire almeno fetch automatico, estrazione dei campi necessari e archiviazione dei JSON in GitHub.

## Avvio manuale

Dopo che il workflow è disponibile sul branch scelto, da **Actions → Sonda assenze (solo audit, fonti autorizzate) → Run workflow**:

1. Compilare `report_window` (ad esempio `16–19/10/2026`, `23–26/10/2026` o `confronto dopo comunicato del martedì`).
2. Impostare ogni consenso ufficiale su `yes` solo se l'autorizzazione scritta copre esattamente quelle attività. Default `no` non esegue rete.
3. Incollare gli URL HTTPS **diretti** dei documenti appena pubblicati: PDF del Giudice Sportivo, PDF RFEF della giornata conclusa, articolo LFP disciplinare. Se URL o consenso mancano, il risultato è `not_read`, con motivo e senza richiesta.
4. Serie A: per una lista completa dei diffidati aggiungere gli URL di tutti i comunicati precedenti dalla prima giornata, uno per riga; confermare `serie_a_history_complete=yes` solo se non manca alcun documento o parte. Massimo 20 PDF storici per run. Senza copertura completa il referto mostra solo i diffidati osservati tra i calciatori ammoniti nel documento corrente e dichiara l'elenco generale non calcolabile.
5. RFEF: il nome dei PDF non è stabile (una giornata può essere divisa in parti). Usare l'URL ufficiale esatto trovato nell'archivio; non indovinare il link della giornata successiva.

I sei job sono indipendenti. Per ogni pagina il client usa User-Agent `SoccerMath2.0-assenze-audit/1.0 (+https://github.com/iFelice/SoccerMath2.0)`, effettua una richiesta senza retry/redirect e attende 3 secondi prima del fetch. I job esclusi dai termini non contattano la fonte.

## Output

- `audit/data/assenze/<YYYY-MM-DD_HHMM>/<fonte>.json`: snapshot con URL, timestamp, stato, codice HTTP, byte, documento trovato, righe estratte, dati letti e squadre non abbinate. Il suffisso orario è UTC.
- `audit/results/sonda_assenze.md`: regola dichiarata prima dei numeri, diagnostica per ogni fonte, liste estratte, motivi di non lettura e lacune.
- `GITHUB_STEP_SUMMARY`: copia del referto del run.

Il job finale committa snapshot e referto sul branch dal quale è stato lanciato il dispatch. Il workflow non si avvia su schedule, push o pull request.

## Regole di verità

- Una fonte è `read` solo con HTTP 200, documento riconosciuto e almeno una riga disciplinare pertinente. HTTP != 200, documento vuoto/assente, schema cambiato o zero righe danno `not_read` con motivo; mai «nessuno squalificato».
- Serie A: i provvedimenti di squalifica provengono dalla sezione ufficiale delle squalifiche. I progressivi dei cartellini servono soltanto ai diffidati, con soglie 5, 9, 13, 16, 18 e ogni ammonizione dalla 19ª. Nessuna squalifica è ricostruita dai cartellini.
- Nessun fuzzy matching: `team_aliases.clean_name` viene applicato prima, poi si usano alias ufficiali dichiarati in `team_mapping.py`; `display_names.display_name` è solo presentazione. I non abbinati sono riportati.
- Un'eventuale fonte non ufficiale potrà diventare affidabile solo dopo concordanza esatta di tutti i calciatori con la fonte ufficiale per due turni consecutivi; le fonti attualmente escluse non ricevono confronti né un punteggio `0/2` interpretato come discordanza.
- La sonda non raccoglie infortuni o formazioni probabili. Qualsiasi dato futuro di quel tipo deve includere fonte e ora di aggiornamento.

## Test

`audit/test_assenze_sonda.py` non effettua rete: verifica parser puri sui fixture testuali ridotti RFEF/LFP, il formato Serie A su input sintetico, mapping, soglie e casi HTTP/schema/errori. Il PDF CU n. 47 dichiarato come fixture locale Serie A non era presente nel checkout; il test sul PDF originale resta da lanciare dopo il suo ripristino. Il test sintetico non viene presentato come prova sul PDF reale.
