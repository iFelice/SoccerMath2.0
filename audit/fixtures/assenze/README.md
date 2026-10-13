# Fixture offline della sonda assenze

- `laliga_j7_2026-09-23.txt` è una trascrizione ridotta delle righe disciplinari del PDF RFEF ufficiale della 7ª giornata, comunicato del 23/09/2026. URL: <https://rfef.es/sites/default/files/sanciones/Primera_Division_J7.pdf>.
- `ligue1_decisions_2026-09-23.txt` è una trascrizione ridotta dell'articolo ufficiale LFP del 23/09/2026, pubblicato il 24/09/2026. URL: <https://ligue1.com/fr/articles/l1_article_5894-discipline-toutes-les-decisions-du-23-septembre>.
- I fixture testuali conservano solo il minimo testo necessario per verificare il parser offline; non sono i PDF/HTML originali. La sonda non scarica né salva il documento sorgente completo.
- Il PDF Serie A n. 47 indicato come `audit/fixtures/squalifiche/serie_a_cu47_2026-10-13.pdf` non è presente nel checkout. Non è stato ricostruito né sostituito con una trascrizione: il test Serie A usa un estratto sintetico del formato e il test sul PDF reale resta da eseguire quando il file sarà ripristinato.

I permessi scritti per le fonti ufficiali sono stati dichiarati dall'operatore il 13/10/2026. Il workflow richiede comunque una conferma esplicita per fonte ad ogni `workflow_dispatch`; l'autorizzazione non è inclusa nel repository.
