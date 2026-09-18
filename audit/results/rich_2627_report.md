# Fonte dati ricca per la stagione in corso (2627) — referto di verifica

Referto GENERATO da `python audit/rich_db_audit.py` (non riscritto a mano).

- generato il: `2026-09-18T12:47:27Z` _(unica riga variabile fra due rigenerazioni)_
- rigenerabile con: `python audit/rich_db_audit.py`
- snapshot della fonte: `audit/data/rich_2627_snapshot` (5 CSV grezzi, byte per byte, + `manifest.json`)
- file della commessa: `SoccerMath/update_db_rich.py` (nuovo), `SoccerMath/test_update_db_rich.py` (nuovo), `SoccerMath/config.py` (solo il campo `fd_code` in `LEAGUES_CONFIG`), `audit/rich_db_audit.py` (nuovo), `audit/data/rich_2627_snapshot/` (byte grezzi della fonte), `audit/results/rich_2627_report.{md,json}`
- verifica eseguita su una COPIA ISOLATA del database (`cartella temporanea; --work-dir per ispezionarla`): i `*_Live.csv` di produzione **non sono stati modificati** (commessa in STOP, vedi §1.6).

## 0. Sintesi degli esiti

| Criterio | Esito | Misura |
|---|---|---|
| A' — invarianza di produzione (ri-verifica) | VERDE | test 1X2 verde prima e dopo; fixture identico (sì); 6 colonne: 0 celle cambiate; righe 231→231 |
| B' — idempotenza (ri-verifica) | VERDE | secondo run: 0 celle riscritte, sha256 identici per tutte e 5 le leghe |
| C' — non regressione del bug di dedup (ri-verifica) | il bug si riproduce | 23158 celle ricche azzerate dal merge di update_db.py (prerequisito dichiarato per la commessa di integrazione) |
| D' — copertura ≥ 95% sulle appaiabili | VERDE | Serie A: 100.0% (40/40 appaiabili; 100.0% su tutte le concluse); Premier League: 100.0% (45/45 appaiabili; 100.0% su tutte le concluse); La Liga: 100.0% (68/68 appaiabili; 90.7% su tutte le concluse); Bundesliga: 100.0% (31/31 appaiabili; 100.0% su tutte le concluse); Ligue 1: 100.0% (40/40 appaiabili; 100.0% su tutte le concluse) |
| E' — test unitari del merge | VERDE | 43 test offline, tutti verdi (34 della commessa precedente + 9 nuovi sugli alias e sulla classificazione) |

STOP della commessa precedente (punto 1d): **SÌ** — 5 squadre su 5 leghe hanno un nome divergente fra il CSV football-data e il *_Live.csv (dettaglio in §1.6)
- risolto da: commessa 1bis: tabella FD_MERGE_ALIASES dentro update_db_rich.py

## 1. Verifica preliminare (punto 1 della commessa)

I 5 CSV sono stati scaricati una volta, grezzi, da un workflow GitHub Actions
temporaneo `.github/workflows/fd2627_fetch_tmp.yml` perché il dominio
`www.football-data.co.uk` **non è raggiungibile** dall'ambiente in cui lavoro
(TLS chiuso dal proxy di rete: `curl` e `requests` danno entrambi errore).
Il workflow (`contents: write`, nessun segreto, nessun commit nel repository:
pubblica i byte su una cartella temporanea del branch) è stato **rimosso prima del
commit finale**; i byte scaricati sono conservati in `audit/data/rich_2627_snapshot/`.

### 1.1 Download: HTTP status e righe (punto 1a)

| Lega | Codice | HTTP | byte | Content-Length | righe | prima data | ultima data | Last-Modified |
|---|---|---|---|---|---|---|---|---|
| Serie A | I1 | 200 | 19221 | 19221 | 40 | 2026-08-22 | 2026-09-14 | Mon, 14 Sep 2026 22:57:17 UTC |
| Premier League | E0 | 200 | 20004 | 20004 | 40 | 2026-08-21 | 2026-09-14 | Mon, 14 Sep 2026 22:57:16 UTC |
| La Liga | SP1 | 200 | 24763 | 24763 | 51 | 2026-08-15 | 2026-09-14 | Mon, 14 Sep 2026 22:57:17 UTC |
| Bundesliga | D1 | 200 | 13395 | 13395 | 27 | 2026-08-28 | 2026-09-13 | Mon, 14 Sep 2026 22:57:18 UTC |
| Ligue 1 | F1 | 200 | 17596 | 17596 | 36 | 2026-08-21 | 2026-09-13 | Mon, 14 Sep 2026 22:57:18 UTC |

Tutte e 5 le risposte arrivano dopo un `302` da `www.football-data.co.uk` a
`football-data.co.uk` (seguendo il redirect), `content-type: text/csv`.

### 1.2 Colonne: confronto insiemistico con l'header di `<Prefix>_2025.csv` (punto 1b)

| Lega | colonne CSV 2627 | colonne storico 2025 | perse | nuove |
|---|---|---|---|---|
| Serie A | 113 | 131 | 32 | 14 |
| Premier League | 114 | 132 | 32 | 14 |
| La Liga | 113 | 131 | 32 | 14 |
| Bundesliga | 113 | 131 | 32 | 14 |
| Ligue 1 | 113 | 131 | 32 | 14 |

Colonne perse (identiche per le 5 leghe, 32): `BMGMH`, `BMGMD`, `BMGMA`, `CLH`, `CLD`, `CLA`, `LBH`, `LBD`, `LBA`, `PSH`, `PSD`, `PSA`, `P>2.5`, `P<2.5`, `PAHH`, `PAHA`, `BMGMCH`, `BMGMCD`, `BMGMCA`, `CLCH`, `CLCD`, `CLCA`, `LBCH`, `LBCD`, `LBCA`, `PSCH`, `PSCD`, `PSCA`, `PC>2.5`, `PC<2.5`, `PCAHH`, `PCAHA`

Colonne nuove (identiche per le 5 leghe, 14): `HxG`, `AxG`, `PPH`, `PPD`, `PPA`, `SKBH`, `SKBD`, `SKBA`, `PPCH`, `PPCD`, `PPCA`, `SKBCH`, `SKBCD`, `SKBCA`

Eccezione: il CSV dell'E0 porta anche `Referee` (colonna che l'header storico di
`Premier_2025.csv` ha già e che le altre 4 leghe non hanno): il merge per colonna
la lascia dov'è e la valorizza solo per la Premier League.

### 1.3 Encoding (punto 1c)

| Lega | BOM | decodifica usata | righe CRLF | sha256 header (prime 16) |
|---|---|---|---|---|
| Serie A | UTF-8 con BOM | utf-8-sig | 41 | a1ad39714cb46bc1… |
| Premier League | UTF-8 con BOM | utf-8-sig | 41 | ce797505897153cd… |
| La Liga | UTF-8 con BOM | utf-8-sig | 52 | a1ad39714cb46bc1… |
| Bundesliga | UTF-8 con BOM | utf-8-sig | 28 | a1ad39714cb46bc1… |
| Ligue 1 | UTF-8 con BOM | utf-8-sig | 37 | a1ad39714cb46bc1… |

Atteso UTF-8-SIG per stagioni >= 2425: **confermato** su tutte e 5 le leghe (BOM `EF BB BF`, terminatore CRLF, decodifica senza errori).

### 1.4 Nomi squadra e `config.clean_name()` (punto 1d)

| Lega | squadre distinte | clean_name in MARKET_VALUES | clean_name NON in MARKET_VALUES | clean_name NON presente nel *_Live.csv |
|---|---|---|---|---|
| Serie A | 20 | 20 | 0 | 0 |
| Premier League | 20 | 18 | 2 | 2 |
| La Liga | 20 | 18 | 2 | 2 |
| Bundesliga | 18 | 17 | 1 | 1 |
| Ligue 1 | 18 | 18 | 0 | 0 |

Dettaglio delle squadre il cui `clean_name` **non** è in `MARKET_VALUES` (sono le candidate al disallineamento):

| Lega | nome nel CSV 2627 | clean_name | già usato nel *_Live.csv |
|---|---|---|---|
| Premier League | `Coventry` | `Coventry` | NO |
| Premier League | `Hull` | `Hull` | NO |
| La Liga | `La Coruna` | `La Coruna` | NO |
| La Liga | `Malaga` | `Malaga` | NO |
| Bundesliga | `Paderborn` | `Paderborn` | NO |

### 1.5 Copertura grezza: partite nel CSV vs partite nel `*_Live.csv` (punto 1e)

| Lega | partite nel CSV 2627 | righe nel *_Live.csv | chiavi uniche nel *_Live.csv | solo CSV | solo Live |
|---|---|---|---|---|---|
| Serie A | 40 | 40 | 40 | 0 | 0 |
| Premier League | 40 | 45 | 40 | 7 | 7 |
| La Liga | 51 | 75 | 58 | 9 | 16 |
| Bundesliga | 27 | 31 | 27 | 3 | 3 |
| Ligue 1 | 36 | 40 | 36 | 0 | 0 |

Nota: le righe `*_Live.csv` sono più delle chiavi uniche perché `update_db.py`
scrive il nome breve dell'API e, in alcuni casi, la stessa partita ricompare
anche con il nome canonico (`Dortmund-HSV` e `Dortmund-Hamburg`, `Alavés` e
`Alaves`): il merge per colonna tratta le due righe come la stessa partita.

### 1.6 Nomi divergenti e tabella alias di merge (commessa 1bis)

La commessa precedente ha trovato **5 squadre** il cui nome nel CSV
football-data.co.uk non coincide con quello già usato nel `*_Live.csv`
(canone dell'API). Le rose 2026/27 sono confermate corrette su entrambe le
fonti: il disallineamento è puramente ortografico.

| Lega | nome nel *_Live.csv (canone di produzione) | nome nel CSV football-data | alias di merge |
|---|---|---|---|
| Premier League | `Coventry City` | `Coventry` | `Coventry` → `Coventry City` |
| Premier League | `Hull City` | `Hull` | `Hull` → `Hull City` |
| La Liga | `Deportivo` | `La Coruna` | `La Coruna` → `Deportivo` |
| La Liga | `Málaga` | `Malaga` | `Malaga` → `Málaga` |
| Bundesliga | `SC Paderborn` | `Paderborn` | `Paderborn` → `SC Paderborn` |

La soluzione NON tocca `clean_name`, `TEAM_NAME_MAP`, `UNDERSTAT_NAME_MAP`,
`team_aliases.py` o `MARKET_VALUES`: quelli normalizzano l'API sul canone
football-data e sono il canone di **produzione**. La commessa 1bis aggiunge la
direzione opposta, una tabella di alias che vive e muore dentro
`update_db_rich.py` e serve solo a calcolare la chiave di join:

```python
FD_MERGE_ALIASES = {   # nome CSV football-data -> nome gia' nel *_Live.csv
    'Coventry': 'Coventry City',
    'La Coruna': 'Deportivo',
    'Hull': 'Hull City',
    'Malaga': 'Málaga',
    'Paderborn': 'SC Paderborn',
}
```

- lookup **esatto**, 5 voci note, nessun fuzzy (un sesto caso resta fuori e
  finisce nel referto come «nome mancante in alias»);
- applicata **prima** di `clean_name` e **solo** al lato football-data.co.uk
  della chiave: il file esistente è il canone e non viene aliasato;
- `HomeTeam`/`AwayTeam` del CSV risultante restano quelli di oggi: le colonne
  sono protette, quindi il nome alias non viene mai scritto nel database.

#### Righe duplicate nei `*_Live.csv` (fuori dal perimetro 1bis)

Righe totali **231**, chiavi uniche **201**: **30 righe duplicate** (`Alavés`/`Alaves`,
`Rayo Vallecano`/`Vallecano`, `Espanyol`/`Espanol`, `Atleti`/`Ath Madrid`, ...:
`update_db.py` deduce i nomi grezzi dell'API, non su quelli puliti). Il merge
per colonna tratta le righe duplicate come la stessa partita (la riga sorgente
viene riusata, non contesa) e **non** le deduplica: la deduplica è produzione e
va con l'integrazione (1ter), insieme al merge per colonna dentro `update_db.py`.
Interferenza con i conteggi: nessuna — la copertura è calcolata sulle righe del
`*_Live.csv`, duplicate comprese, e ogni riga duplicata riceve gli stessi valori.

### 1.7 Deriva delle colonne bookmaker e colonne "stabili"

| Famiglia | 2022 | 2023 | 2024 | 2025 | 2627 | verdetto |
|---|---|---|---|---|---|---|
| B365* | 14 | 14 | 14 | 14 | 14 | stabile |
| Avg* | 14 | 14 | 14 | 14 | 14 | stabile |
| Max* | 14 | 14 | 14 | 14 | 14 | stabile |
| PS* | 6 | 6 | 6 | 6 | 0 | NON stabile |

**Verifica dell'assunto della commessa (“il codice a valle deve usare solo
B365*/Avg*/Max*/PS*, che sono stabili”): l'assunto è VERO per `B365*`, `Avg*` e
`Max*` (presenti in tutte e 5 le stagioni, 2022 → 2026/27) ed è **FALSO per `PS*`**,
che è presente in 2022/23, 2023/24, 2024/25 e 2025/26 e **assente nel 2026/27**
(al suo posto compaiono `PP*` e `SKB*`). Conseguenza operativa: qualsiasi calcolo
che legga Pinnacle da `PSH/PSD/PSA` + `PSCH/PSCD/PSCA` (per esempio
`audit/diagnose_clv_pinnacle.py`) **non è calcolabile sul 2026/27** neanche dopo
l'arricchimento. La chiusura di Bet365 (`B365CH/B365CD/B365CA`) è invece presente,
quindi un CLV Bet365 (apertura `B365H` vs chiusura `B365CH`) lo è.

Prefissi bookmaker presenti per stagione (famiglie 1X2 e closing):

- **2022**: `Avg`, `AvgAH`, `AvgC`, `B365`, `B365C`, `BW`, `BWC`, `IW`, `IWC`, `Max`, `MaxAH`, `MaxC`, `PAH`, `PCAH`, `PS`, `PSC`, `VC`, `VCC`, `WH`, `WHC`
- **2023**: `Avg`, `AvgAH`, `AvgC`, `B365`, `B365C`, `BW`, `BWC`, `IW`, `IWC`, `Max`, `MaxAH`, `MaxC`, `PAH`, `PCAH`, `PS`, `PSC`, `VC`, `VCC`, `WH`, `WHC`
- **2024**: `1XB`, `1XBC`, `Avg`, `AvgAH`, `AvgC`, `B365`, `B365C`, `BF`, `BFC`, `BFE`, `BFEAH`, `BFEC`, `BW`, `BWC`, `Max`, `MaxAH`, `MaxC`, `PAH`, `PCAH`, `PS`, `PSC`, `WH`, `WHC`
- **2025**: `Avg`, `AvgAH`, `AvgC`, `B365`, `B365C`, `BFD`, `BFDC`, `BFE`, `BFEAH`, `BFEC`, `BMGM`, `BMGMC`, `BV`, `BVC`, `BW`, `BWC`, `CL`, `CLC`, `LB`, `LBC`, `Max`, `MaxAH`, `MaxC`, `PAH`, `PCAH`, `PS`, `PSC`
- **2627**: `Avg`, `AvgAH`, `AvgC`, `B365`, `B365C`, `BFD`, `BFDC`, `BFE`, `BFEAH`, `BFEC`, `BV`, `BVC`, `BW`, `BWC`, `Max`, `MaxAH`, `MaxC`, `PP`, `PPC`, `SKB`, `SKBC`

Nessuno schema di colonne è assunto dal codice: `update_db_rich.py` unisce
l'unione delle colonne presenti e riempie solo le celle vuote.

## 2. Criteri di accettazione (A'/B'/C'/E' ri-verificati, D' riscritto)

### A') Invarianza di produzione (ri-verifica)

| Controllo | Esito | Misura |
|---|---|---|
| copia isolata == produzione all'ingresso | IDENTICA | sha256 dei 5 *_Live.csv confrontati prima del run |
| test_pt19_totali_invariance.py prima | VERDE | Ran 2 tests — OK |
| test_pt19_totali_invariance.py dopo | VERDE | Ran 2 tests — OK |
| fixture 1x2 rigenerato prima/dopo (byte a byte) | IDENTICO | 52939 byte, sha256 654e166bbcef3b56351472a1e7c29cc2… |
| 6 colonne lette da app.py | IDENTICHE | 0 celle diverse su 1386 |
| righe del database | IDENTICHE | 231 prima, 231 dopo |
| colonne | SOLO AGGIUNTE | Serie A: 132→146; Premier League: 133→147; La Liga: 132→146; Bundesliga: 132→146; Ligue 1: 132→146 |
| 6 colonne: DB di produzione vs copia arricchita | IDENTICHE | 0 celle diverse su 1386 fra SoccerMath/database/ e la copia isolata dopo il run |
| chiavi (Date, clean H, clean A) | IDENTICHE | 0 rimosse, 0 aggiunte |

Il test `SoccerMath/test_pt19_totali_invariance.py` è stato eseguito **due volte**
sulla copia isolata: prima dell'arricchimento e dopo.

```
prima:  Ran 2 tests — OK
dopo:   Ran 2 tests — OK
```

Le 6 colonne lette da `app.py` (`Date`, `HomeTeam`, `AwayTeam`, `FTHG`, `FTAG`, `FTR`)
sono confrontate cella per cella prima e dopo: differenze **0**.

Righe sulle chiavi `(Date, clean_name(Home), clean_name(Away))`:

| Controllo | Prima | Dopo | Esito |
|---|---|---|---|
| righe totali | 231 | 231 | uguali |
| chiavi uniche | 201 | 201 | uguali |
| chiavi rimosse | — | 0 | 0 |
| chiavi aggiunte | — | 0 | 0 |
| colonne | 661 | 731 | solo aggiunte |

Fixture `test_fixtures/1x2_invariance.json` rigenerato prima e dopo e confrontato
byte a byte:

```
before: sha256 654e166bbcef3b56351472a1e7c29cc2b711f8966a3d7c9faa618b6b3e7d28d0  (52939 byte)
after : sha256 654e166bbcef3b56351472a1e7c29cc2b711f8966a3d7c9faa618b6b3e7d28d0  (52939 byte)
identici: True
```

Confronto con il fixture committato (`SoccerMath/test_fixtures/1x2_invariance.json`,
sha256 `b25e1c16efe6e680…`): diverso dal fixture committato: il database è cresciuto rispetto a quando il fixture fu generato (partite 2026/27 aggiunte dopo), quindi il campione rigenerato è un altro; il confronto valido è prima/dopo l'arricchimento

### B') Idempotenza (ri-verifica)

| Lega | sha256 dopo run 1 | sha256 dopo run 2 | celle riscritte nel run 2 | Esito |
|---|---|---|---|---|
| Serie A | 20036662832f0572… | 20036662832f0572… | 0 | identico |
| Premier League | d4c1a622a8739b53… | d4c1a622a8739b53… | 0 | identico |
| La Liga | 23d3f572b78dbeca… | 23d3f572b78dbeca… | 0 | identico |
| Bundesliga | 5866df9ef470d57d… | 5866df9ef470d57d… | 0 | identico |
| Ligue 1 | eb1a12151263360f… | eb1a12151263360f… | 0 | identico |

Esito: **VERDE** — il secondo run non produce alcun diff sui CSV (celle riscritte: 0).

### C') Non regressione del bug di dedup (ri-verifica)

Simulazione della sequenza reale `update_db_rich.py → update_db.py → update_db_rich.py`.
`update_db.py` non è stato eseguito (richiede la chiave API e scriverebbe sui file
di produzione): ne è stata replicata **fedelmente la logica di merge** (righe 143-160:
`pd.concat([df_old, df_new])` + `drop_duplicates(subset=[Date,HomeTeam,AwayTeam],
keep="last")` + ordinamento per data), con `df_new` = le righe API delle stesse
partite (le 10 colonne che l'API espone, stessi nomi squadra: il caso migliore).

| Lega | celle ricche dopo run 1 | celle ricche dopo update_db.py | azzerate | recuperate dal run 3 di update_db_rich |
|---|---|---|---|---|
| Serie A | 4119 | 0 | 4119 | 4119 |
| Premier League | 4679 | 0 | 4679 | 4679 |
| La Liga | 7033 | 0 | 7033 | 7033 |
| Bundesliga | 3191 | 0 | 3191 | 3191 |
| Ligue 1 | 4136 | 0 | 4136 | 4136 |

Esito: **il bug si riproduce**

**Prerequisito per la commessa di integrazione (da riportare, senza modificare
`update_db.py` in questa sede):**

> il merge dentro update_db.py va rifatto per colonna (come in update_db_rich.merge_columns) PRIMA di integrare update_db_rich.py nel workflow: con il concat + drop_duplicates(keep="last") attuale, il primo run di update_db.py dopo l'arricchimento azzera 23158 celle delle colonne ricche (tutte: la riga API ha solo 10 colonne e vince sul duplicato).
> Il terzo run di update_db_rich.py le recupera, ma solo perché riscarica tutto da football-data.co.uk: finché update_db.py non cambia, il dato ricco è garantito solo se update_db_rich.py gira DOPO update_db.py, e comunque la finestra in cui il dato è azzerato resta reale.

### D') Copertura di `B365H` e `HS` (soglia 95% sulle righe appaiabili)

Base del criterio: partite concluse **meno** le righe in categoria «ritardo della
fonte» (fisiologiche, dichiarate una per una qui sotto). La copertura grezza su
tutte le partite concluse è riportata accanto, non al posto.

| Lega | concluse | escluse (ritardo fonte) | appaiabili | coperti B365H | % su appaiabili (D') | % su tutte (grezza) | atteso commessa | Esito |
|---|---|---|---|---|---|---|---|---|
| Serie A | 40 | 0 | 40 | 40 | 100.0% | 100.0% | 40/40 = 100.0% | OK |
| Premier League | 45 | 0 | 45 | 45 | 100.0% | 100.0% | 45/45 = 100.0% | OK |
| La Liga | 75 | 7 | 68 | 68 | 100.0% | 90.7% | 69/75 = 92.0% | OK |
| Bundesliga | 31 | 0 | 31 | 31 | 100.0% | 100.0% | 31/31 = 100.0% | OK |
| Ligue 1 | 40 | 0 | 40 | 40 | 100.0% | 100.0% | 40/40 = 100.0% | OK |

Le due sonde coincidono sempre (arrivano dalla stessa riga del CSV): `HS` = Serie A 40/40; Premier League 45/45; La Liga 68/68; Bundesliga 31/31; Ligue 1 40/40.

Esito complessivo: **VERDE**. Leghe sotto soglia: nessuna.

#### Atteso vs ottenuto

| Lega | atteso (commessa 1bis) | ottenuto (concluse) | ottenuto (appaiabili) | differenza |
|---|---|---|---|---|
| Serie A | 40/40 = 100.0% | 40/40 = 100.0% | 40/40 = 100.0% | nessuna |
| Premier League | 45/45 = 100.0% | 45/45 = 100.0% | 45/45 = 100.0% | nessuna |
| La Liga | 69/75 = 92.0% | 68/75 = 90.7% | 68/68 = 100.0% | 68/75 = 90.7% contro 69/75 = 92.0% atteso: -1 riga |
| Bundesliga | 31/31 = 100.0% | 31/31 = 100.0% | 31/31 = 100.0% | nessuna |
| Ligue 1 | 40/40 = 100.0% | 40/40 = 100.0% | 40/40 = 100.0% | nessuna |

- **La Liga**: 68/75 = 90.7% contro 69/75 = 92.0% atteso: -1 riga. Righe non coperte, una per una:
  - `15/09/2026 Vallecano - Espanol`: nessuna squadra coperta da alias: era già contata come ritardo della fonte anche senza alias.
  - `15/09/2026 Alaves - Valencia`: nessuna squadra coperta da alias: era già contata come ritardo della fonte anche senza alias.
  - `15/09/2026 Elche - Real Madrid`: nessuna squadra coperta da alias: era già contata come ritardo della fonte anche senza alias.
  - `16/09/2026 Levante - Ath Bilbao`: nessuna squadra coperta da alias: era già contata come ritardo della fonte anche senza alias.
  - `16/09/2026 Deportivo - Sevilla`: porta una squadra coperta da alias (Deportivo): senza alias era conteggiata fra i «nomi mancanti in alias», con l'alias è riclassificata come ritardo della fonte.
  - `16/09/2026 Ath Madrid - Osasuna`: nessuna squadra coperta da alias: era già contata come ritardo della fonte anche senza alias.
  - `16/09/2026 Barcelona - Santander`: nessuna squadra coperta da alias: era già contata come ritardo della fonte anche senza alias.
  - Effetto netto: le righe di ritardo fonte passano da 6 a 7 e la base D' da 69 a 68: `16/09/2026 Deportivo - Sevilla` non è coperta perché la fonte non ha ancora quella partita (ultimo aggiornamento del CSV: 14/09/2026), non per un difetto di allineamento. La soglia non è stata toccata per far tornare il numero.

Righe escluse dal denominatore (ritardo della fonte), per nome:

| Lega | Data | Partita | Motivo |
|---|---|---|---|
| La Liga | 15/09/2026 | Vallecano - Espanol | partita successiva all'ultimo aggiornamento del CSV football-data (ultima data presente: 14/09/2026) |
| La Liga | 15/09/2026 | Alaves - Valencia | partita successiva all'ultimo aggiornamento del CSV football-data (ultima data presente: 14/09/2026) |
| La Liga | 15/09/2026 | Elche - Real Madrid | partita successiva all'ultimo aggiornamento del CSV football-data (ultima data presente: 14/09/2026) |
| La Liga | 16/09/2026 | Levante - Ath Bilbao | partita successiva all'ultimo aggiornamento del CSV football-data (ultima data presente: 14/09/2026) |
| La Liga | 16/09/2026 | Deportivo - Sevilla | partita successiva all'ultimo aggiornamento del CSV football-data (ultima data presente: 14/09/2026) |
| La Liga | 16/09/2026 | Ath Madrid - Osasuna | partita successiva all'ultimo aggiornamento del CSV football-data (ultima data presente: 14/09/2026) |
| La Liga | 16/09/2026 | Barcelona - Santander | partita successiva all'ultimo aggiornamento del CSV football-data (ultima data presente: 14/09/2026) |

Righe appaiabili ma non coperte (queste sì sono un difetto della commessa):

_nessuna: tutte le righe appaiabili sono coperte_

### E') Test unitari del merge per colonna (ri-verifica + nuovi)

- file: `SoccerMath/test_update_db_rich.py`
- comando: `python SoccerMath/test_update_db_rich.py`
- test eseguiti: **43**, esito **VERDE**
- rete: nessuna (tutti i test sono offline)

Casi richiesti dalla commessa e presenti nella suite:

- `test_una_colonna_gia_valorizzata_non_viene_sovrascritta` (valore diverso);
- `test_un_nullo_non_sovrascrive_un_valore_esistente` (il caso esplicitamente
  richiesto: una colonna già valorizzata NON viene sovrascritta da un nullo);
- `test_colonne_protette_non_vengono_mai_scritte` (Matchday e risultati);
- `test_nessuna_riga_aggiunta_o_rimossa`, `test_idempotenza_del_merge`,
  `test_tolleranza_piu_meno_un_giorno`, `test_unione_delle_colonne_con_ordine_stabile`,
  `test_righe_duplicate_sulla_stessa_chiave_riusano_la_sorgente`,
  `test_merge_non_usa_concat_ne_drop_duplicates`, `test_scrittura_atomica`,
  `test_exit_code_non_zero_con_sorgente_assente`.

## 3. Partite non appaiate (tutte le leghe)

| Lega | Data | Partita (come nel *_Live.csv) | chiave pulita | categoria | motivo |
|---|---|---|---|---|---|
| La Liga | 15/09/2026 | Vallecano - Espanol | Vallecano / Espanol | ritardo della fonte | partita successiva all'ultimo aggiornamento del CSV football-data (ultima data presente: 14/09/2026) |
| La Liga | 15/09/2026 | Alaves - Valencia | Alaves / Valencia | ritardo della fonte | partita successiva all'ultimo aggiornamento del CSV football-data (ultima data presente: 14/09/2026) |
| La Liga | 15/09/2026 | Elche - Real Madrid | Elche / Real Madrid | ritardo della fonte | partita successiva all'ultimo aggiornamento del CSV football-data (ultima data presente: 14/09/2026) |
| La Liga | 16/09/2026 | Levante - Ath Bilbao | Levante / Ath Bilbao | ritardo della fonte | partita successiva all'ultimo aggiornamento del CSV football-data (ultima data presente: 14/09/2026) |
| La Liga | 16/09/2026 | Deportivo - Sevilla | Deportivo / Sevilla | ritardo della fonte | partita successiva all'ultimo aggiornamento del CSV football-data (ultima data presente: 14/09/2026) |
| La Liga | 16/09/2026 | Ath Madrid - Osasuna | Ath Madrid / Osasuna | ritardo della fonte | partita successiva all'ultimo aggiornamento del CSV football-data (ultima data presente: 14/09/2026) |
| La Liga | 16/09/2026 | Barcelona - Santander | Barcelona / Santander | ritardo della fonte | partita successiva all'ultimo aggiornamento del CSV football-data (ultima data presente: 14/09/2026) |

Totale: 7 righe non appaiate su 231 righe complessive.

Ripartizione per categoria (le due categorie NON si sommano in un unico
numero, per costruzione):

| Categoria | Righe | Significato |
|---|---|---|
| nome mancante in alias | 0 | difetto di allineamento di questa commessa: conta nel denominatore |
| ritardo della fonte | 7 | fonte football-data.co.uk indietro rispetto all'API: fisiologica, esclusa dal denominatore e dichiarata per nome |
| partita assente nel CSV | 0 | né nome né data: da spiegare riga per riga (atteso 0) |

Passaggi di allineamento: prima data esatta, poi tolleranza ±1 giorno a parità di
squadre pulite. Righe appaiate al secondo passaggio: 0.

## 4. Come rigenerare questo referto

```
python audit/rich_db_audit.py            # usa lo snapshot committato
python audit/rich_db_audit.py --work-dir /tmp/rich2627   # per ispezionare i file
```

Il referto dipende solo da: (a) gli sha256 dei 5 CSV in
`audit/data/rich_2627_snapshot/`, (b) gli sha256 dei `*_Live.csv` all'ingresso,
(c) il codice di `SoccerMath/`. Se uno di questi cambia, i numeri cambiano e la
differenza va letta, non assorbita: gli hash di ingresso sono qui sotto.

| File | sha256 all'ingresso |
|---|---|
| SoccerMath/database/SerieA_Live.csv | 7d5806355def335491a29be3726b4696… |
| SoccerMath/database/Premier_Live.csv | 3828b845ab60939263eac149a3241a59… |
| SoccerMath/database/LaLiga_Live.csv | f654a0bdcd3698e57a11586e14b24ae3… |
| SoccerMath/database/Bundesliga_Live.csv | 59a2bca40eed52b8fd3f74833788936f… |
| SoccerMath/database/Ligue1_Live.csv | 7ae864a1065d04c2ff34861e1db41189… |

## 5. Applicare l'arricchimento ai file di produzione

In questa commessa i `*_Live.csv` **non sono stati modificati** (STOP del punto 1d).
I comandi per applicarlo, identici a quelli usati nel referto ma senza la copia
isolata, sono:

```
# download reale dalla fonte (5 leghe, stagione derivata da config)
python SoccerMath/update_db_rich.py

# oppure, a partire dallo snapshot committato (nessuna rete)
python SoccerMath/update_db_rich.py --source-dir audit/data/rich_2627_snapshot

# prova senza scrivere
python SoccerMath/update_db_rich.py --dry-run --source-dir audit/data/rich_2627_snapshot
```

Dopo l'applicazione, la sequenza del criterio C resta il prerequisito da
sciogliere prima di integrare il modulo nel workflow.

