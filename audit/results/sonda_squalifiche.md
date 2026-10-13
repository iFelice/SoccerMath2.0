# Sonda squalifiche (archivio player_match, sola lettura)

Run: **2026-10-13T11:19:24Z** · stagione: **2026/27** · archivio: **ASSENTE**.

## Regola dichiarata (prima dei numeri)

Le squalifiche entrano nella scheda partita **solo se**:

1. l'archivio `player_match` copre **tutte** le partite giocate della stagione in corso (soglia dichiarata: 100% dei `*_Live.csv`, zero mancanti);
2. **tutti** i casi verificati su fonti pubbliche concordano con quello che mostra l'archivio (almeno 3 casi).

Esito di questo run: **archivio non disponibile in questo ambiente** → le squalifiche NON entrano nella scheda (e non devono: la regola non e' soddisfatta).

## Stato dell'archivio

**Cosa manca.** I file `player_match_<lega>.json` non sono versionati: li produce il workflow `ppda_player_verify.yml`, che gira in sola lettura (`permissions: contents: read`) e li pubblica come **artifact** (`ppda-player-verify-<run_id>`, dentro la cartella `database/`). In questo giro l'archivio non c'e': nessun `player_match_*.json` in nessuno dei percorsi cercati. Senza quei file non si possono misurare le tre cose chieste: ultima partita per lega, partite 2026/27 coperte contro i `*_Live.csv`, e le squalifiche del prossimo turno. Non e' un limite della sonda: e' l'archivio che va scaricato dove la sonda lo cerca.

**Ultimo archivio prodotto (fatti misurati).**

* run **37917985080** del workflow `ppda_player_verify.yml`: success, 2026-10-09T10:30:09Z → 2026-10-09T11:14:31Z (**44m22s**), evento `push`;
* artifact **ppda-player-verify-37917985080** (id 11612646869), 10030903 byte, creato il 2026-10-09T11:14:27Z, **scade il 2026-10-23T11:14:24Z**;
* tutti i passi del job sono `success` (fonte: `gh api .../actions/runs/37917985080/jobs`): l'acquisizione delle 5 leghe e' arrivata in fondo, quindi un archivio recente esiste — ma **non e' leggibile da qui**.

**Quanto costa aggiornarlo.**

* **zero run**: lanciare a mano il workflow `audit_squalifiche.yml` (`workflow_dispatch`, sola lettura sull'archivio) — prende l'artifact dell'ultimo run del workflow Understat, lo scarica in `audit/output/` (cartella non versionata) ed esegue questa sonda, che riscrive il referto con i numeri;
* la scadenza da rispettare e' quella dell'artifact (sotto): se e' già scaduto va prima rilanciato `ppda_player_verify.yml` (`workflow_dispatch`, nessun cron; durata misurata **44m22s**, 1 richiesta HTTP per partita e una finestra mobile di 5 stagioni per lega) e poi di nuovo `audit_squalifiche.yml`;
* in alternativa, **a mano e senza workflow**: scaricare l'artifact dal browser (GitHub → Actions → run → artifact) e scompattarlo in `audit/output/ppda-player-verify-<run>/database/`;
* in ogni caso la misura e' immediata e offline: `python audit/sonda_squalifiche.py` → il referto si riempie da solo con ultima partita per lega, copertura contro i `*_Live.csv` e casi pubblici.

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

## Come si misura adesso (workflow `audit_squalifiche.yml`)

La misura **non** si fa dall'ambiente di sviluppo (qui l'artifact non e' scaricabile: il download finisce su `*.blob.core.windows.net`, host non raggiungibile). Si fa su GitHub Actions, con il workflow manuale **`audit_squalifiche.yml`** (`workflow_dispatch`, sola lettura sull'archivio; lo lancia Felice):

1. prende l'ultimo run **riuscito** di `ppda_player_verify.yml` (o quello indicato nell'input `run_id`);
2. elenca i suoi artifact e sceglie il piu' recente **non scaduto**;
3. lo scarica in `audit/output/ppda-player-verify-<run_id>/` (cartella non versionata) ed esegue `audit/sonda_squalifiche.py` sulla cartella `database/`;
4. committa **il solo referto** `audit/results/sonda_squalifiche.md` (un ultimo passo verifica che l'archivio non sia entrato nel repository).

**Scadenza da rispettare.** L'ultimo archivio noto e' l'artifact **ppda-player-verify-37917985080** del run **37917985080**, creato il 2026-10-09T11:14:27Z e **scade il 2026-10-23T11:14:24Z** (retention 14 giorni del workflow Understat): `audit_squalifiche.yml` va lanciato **entro quella data**, altrimenti l'artifact non e' piu' scaricabile e serve un nuovo run.

**Se l'artifact e' scaduto**, l'ordine e': (1) rilanciare `ppda_player_verify.yml` (`workflow_dispatch`, durata misurata **44m22s**: 1 richiesta HTTP per partita su ~7.000 partite); (2) lanciare `audit_squalifiche.yml`, che scrive il referto con i numeri nuovi. Se la sonda non trova l'archivio il workflow **fallisce e non committa**: il referto non viene mai riscritto con un esito inventato.

## Cosa NON fa questa sonda

* non aggiorna l'archivio di una riga: lo legge soltanto; a scaricarlo e' l'artifact del workflow Understat, a misurarlo e' questa sonda (in CI: `audit_squalifiche.yml`, lanciato a mano);
* non lancia nessun workflow da sola e non fa rete;
* non riscrive le regole delle ammonizioni: quelle vivono in `audit/squalifiche_feasibility.py` (PR #33);
* non tocca l'app: la scheda partita non mostra squalifiche.

## Note del run

* archivio assente: nessun file player_match_*.json trovato in /home/user/SoccerMath2.0/audit/output/ppda-player-verify-37917985080/database, /home/user/SoccerMath2.0/audit/output/ppda-player-verify/database, /home/user/SoccerMath2.0/audit/output/player_match, /home/user/SoccerMath2.0/audit/data/squalifiche/player_match
