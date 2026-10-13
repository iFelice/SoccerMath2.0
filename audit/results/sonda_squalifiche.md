# Sonda squalifiche (archivio player_match, sola lettura)

Run: **2026-10-13T08:32:35Z** · stagione: **2026/27** · archivio: **ASSENTE**.

## Regola dichiarata (prima dei numeri)

Le squalifiche entrano nella scheda partita **solo se**:

1. l'archivio `player_match` copre **tutte** le partite giocate della stagione in corso (soglia dichiarata: 100% dei `*_Live.csv`, zero mancanti);
2. **tutti** i casi verificati su fonti pubbliche concordano con quello che mostra l'archivio (almeno 3 casi).

Esito di questo run: **archivio non disponibile in questo ambiente** → le squalifiche NON entrano nella scheda (e non devono: la regola non e' soddisfatta).

## Stato dell'archivio

**Cosa manca.** I file `player_match_<lega>.json` non sono versionati: li produce il workflow `ppda_player_verify.yml`, che gira in sola lettura (`permissions: contents: read`) e li pubblica come **artifact**. In questo ambiente l'artifact non e' scaricabile: il download termina con un errore TLS/EOF sul blob di archiviazione di GitHub (`*.blob.core.windows.net`), che non e' raggiungibile dalla sandbox. Senza quei file non si possono misurare le tre cose chieste: ultima partita per lega, partite 2026/27 coperte contro i `*_Live.csv`, e squalifiche del prossimo turno.

**Ultimo archivio prodotto (fatti misurati).**

* run **37917985080** del workflow `ppda_player_verify.yml`: success, 2026-10-09T10:30:09Z → 2026-10-09T11:14:31Z (**44m22s**), evento `push`;
* artifact **ppda-player-verify-37917985080** (id 11612646869), 10030903 byte, creato il 2026-10-09T11:14:27Z, **scade il 2026-10-23T11:14:24Z**;
* tutti i passi del job sono `success` (fonte: `gh api .../actions/runs/37917985080/jobs`): l'acquisizione delle 5 leghe e' arrivata in fondo, quindi un archivio recente esiste — ma **non e' leggibile da qui**.

**Quanto costa aggiornarlo.**

* un run manuale di `ppda_player_verify.yml` (`workflow_dispatch`, nessun cron): la misura nota e' **44m22s**, con 1 richiesta HTTP per partita e una finestra mobile di 5 stagioni per lega;
* oppure **zero run**: scaricare l'artifact già pronto dal browser (GitHub → Actions → run → artifact) e scompattarlo in `audit/output/ppda-player-verify-<run>/database/`;
* poi la misura e' immediata e offline: `python audit/sonda_squalifiche.py` → il referto si riempie da solo con ultima partita per lega, copertura contro i `*_Live.csv` e casi pubblici.

*Nota di costo sull'analisi vera.* Il motore che calcola gli eventi (ammonizioni cumulate, rossi) e' quello della PR #33, `audit/squalifiche_feasibility.py`: su ~226.657 righe giocatore il referto della PR #33 dichiara una precisione dell'1X2 con l'evento in Serie A del **48.1%** contro il **96.8%** della Bundesliga — per questo il motore, da solo, non basta a mettere le squalifiche in scheda: servono i casi pubblici.

**Denominatore minimo: le partite già giocate nei CSV.**

| Lega | Partite giocate 2026/27 nei `*_Live.csv` |
|---|---|
| Serie A | 60 |
| Premier League | 60 |
| La Liga | 78 |
| Bundesliga | 45 |
| Ligue 1 | 54 |

Sono le partite che l'archivio deve contenere **tutte** perché la regola sia soddisfatta: se ne manca una, le squalifiche non entrano nella scheda.

## Cosa NON fa questa sonda

* non aggiorna l'archivio e non lancia nessun workflow (il run e' manuale e lo lancia Felice);
* non riscrive le regole delle ammonizioni: quelle vivono in `audit/squalifiche_feasibility.py` (PR #33);
* non tocca l'app: la scheda partita non mostra squalifiche.

## Note del run

* archivio assente: nessun file player_match_*.json trovato in /home/user/SoccerMath2.0/audit/output/ppda-player-verify-37917985080/database, /home/user/SoccerMath2.0/audit/output/ppda-player-verify/database, /home/user/SoccerMath2.0/audit/output/player_match, /home/user/SoccerMath2.0/audit/data/squalifiche/player_match
