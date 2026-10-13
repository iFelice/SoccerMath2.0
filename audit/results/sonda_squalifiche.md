# Sonda squalifiche (archivio player_match, sola lettura)

Run: **2026-10-13T16:22:31Z** · stagione: **2026/27** · archivio: **/home/runner/work/SoccerMath2.0/SoccerMath2.0/audit/output/ppda-player-verify-38404660658/database**.

## Regola dichiarata (prima dei numeri)

Le squalifiche entrano nella scheda partita **solo se**:

1. l'archivio `player_match` copre **tutte** le partite giocate della stagione in corso (soglia dichiarata: 100% dei `*_Live.csv`, zero mancanti);
2. **tutti** i casi verificati su fonti pubbliche concordano con quello che mostra l'archivio (almeno 3 casi).

Esito di questo run: **NO** — nessun caso pubblico verificabile

## Stato dell'archivio

| Lega | Righe giocatore | Partite distinte | Stagioni | Ultima partita |
|---|---|---|---|---|
| Serie A | 49520 | 3160 | 2022, 2023, 2024, 2025, 2026 | 2026-10-12 |
| Premier League | 47639 | 3160 | 2022, 2023, 2024, 2025, 2026 | 2026-10-12 |
| La Liga | 50050 | 3196 | 2022, 2023, 2024, 2025, 2026 | 2026-10-12 |
| Bundesliga | 39475 | 2536 | 2022, 2023, 2024, 2025, 2026 | 2026-10-11 |
| Ligue 1 | 41460 | 2704 | 2022, 2023, 2024, 2025, 2026 | 2026-10-11 |

## Copertura delle partite giocate della stagione

| Lega | Partite giocate nei CSV | Coperte | Mancanti |
|---|---|---|---|
| Serie A | 60 | 60 | 0 |
| Premier League | 60 | 60 | 0 |
| La Liga | 78 | 78 | 0 |
| Bundesliga | 45 | 45 | 0 |
| Ligue 1 | 54 | 54 | 0 |

## Casi pubblici

_Nessun caso pubblico da confrontare: servono almeno 3 casi con fonte e data._

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
