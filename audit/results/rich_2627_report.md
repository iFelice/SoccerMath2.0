# Fonte dati ricca per la stagione in corso (2627) — referto di verifica

Referto GENERATO da `python audit/rich_db_audit.py` (non riscritto a mano).

- generato il: `2026-09-17T20:15:58Z` _(unica riga variabile fra due rigenerazioni)_
- rigenerabile con: `python audit/rich_db_audit.py`
- snapshot della fonte: `audit/data/rich_2627_snapshot` (5 CSV grezzi, byte per byte, + `manifest.json`)
- file della commessa: `SoccerMath/update_db_rich.py` (nuovo), `SoccerMath/test_update_db_rich.py` (nuovo), `SoccerMath/config.py` (solo il campo `fd_code` in `LEAGUES_CONFIG`), `audit/rich_db_audit.py` (nuovo), `audit/data/rich_2627_snapshot/` (byte grezzi della fonte), `audit/results/rich_2627_report.{md,json}`
- verifica eseguita su una COPIA ISOLATA del database (`cartella temporanea; --work-dir per ispezionarla`): i `*_Live.csv` di produzione **non sono stati modificati** (commessa in STOP, vedi §1.6).

## 0. Sintesi degli esiti

| Criterio | Esito | Misura |
|---|---|---|
| A — invarianza di produzione | VERDE | test 1X2 verde prima e dopo; fixture identico (sì); 6 colonne: 0 celle cambiate; righe 231→231 |
| B — idempotenza | VERDE | secondo run: 0 celle riscritte, sha256 identici per tutte e 5 le leghe |
| C — non regressione del bug di dedup | il bug si riproduce | 21083 celle ricche azzerate dal merge di update_db.py (prerequisito dichiarato per la commessa di integrazione) |
| D — copertura ≥ 90% | ROSSO (sotto soglia: Premier League, La Liga) | Serie A: 100.0%; Premier League: 84.4%; La Liga: 77.3%; Bundesliga: 90.3%; Ligue 1: 100.0% |
| E — test unitari del merge | VERDE | 34 test offline, tutti verdi |

STOP della commessa (punto 1d): **SÌ** — 5 squadre su 5 leghe hanno un nome divergente fra il CSV football-data e il *_Live.csv (dettaglio in §1.6)

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

### 1.6 STOP: nomi della stagione in corso non allineati

**STOP ATTIVO.** La commessa dice: _se anche UNA squadra della stagione in
corso ha un `clean_name` che non coincide con quello già usato nel `*_Live.csv`,
fermarsi e riferire. Non aggiungere alias_. L'esito è questo:

| Lega | nome usato nel *_Live.csv (canonico) | nome nel CSV football-data | conseguenza |
|---|---|---|---|
| Premier League | `Coventry City` (nel *_Live.csv) | `Coventry`, `Hull` | nessun alias aggiunto: le partite restano non appaiate |
| Premier League | `Hull City` (nel *_Live.csv) | `Coventry`, `Hull` | nessun alias aggiunto: le partite restano non appaiate |
| La Liga | `Deportivo` (nel *_Live.csv) | `La Coruna`, `Malaga` | nessun alias aggiunto: le partite restano non appaiate |
| La Liga | `Málaga` (nel *_Live.csv) | `La Coruna`, `Malaga` | nessun alias aggiunto: le partite restano non appaiate |
| Bundesliga | `SC Paderborn` (nel *_Live.csv) | `Paderborn` | nessun alias aggiunto: le partite restano non appaiate |

Nessun alias è stato aggiunto a `team_aliases.py`, `TEAM_NAME_MAP` o
`MARKET_VALUES`, nessuna modifica a `clean_name`: la conseguenza è che le
partite di queste 5 squadre restano **non appaiate** e quindi non coperte
(è la causa diretta dello sforamento della soglia del criterio D).

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

## 2. Criteri di accettazione

### A) Invarianza di produzione

| Controllo | Esito | Misura |
|---|---|---|
| test_pt19_totali_invariance.py prima | VERDE | Ran 2 tests — OK |
| test_pt19_totali_invariance.py dopo | VERDE | Ran 2 tests — OK |
| fixture 1x2 rigenerato prima/dopo (byte a byte) | IDENTICO | 52939 byte, sha256 654e166bbcef3b56351472a1e7c29cc2… |
| 6 colonne lette da app.py | IDENTICHE | 0 celle diverse su 1386 |
| righe del database | IDENTICHE | 231 prima, 231 dopo |
| colonne | SOLO AGGIUNTE | Serie A: 132→146; Premier League: 133→147; La Liga: 132→146; Bundesliga: 132→146; Ligue 1: 132→146 |
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

### B) Idempotenza

| Lega | sha256 dopo run 1 | sha256 dopo run 2 | celle riscritte nel run 2 | Esito |
|---|---|---|---|---|
| Serie A | 20036662832f0572… | 20036662832f0572… | 0 | identico |
| Premier League | 616bfa4fc8f9c228… | 616bfa4fc8f9c228… | 0 | identico |
| La Liga | 935b6a1ea331d61d… | 935b6a1ea331d61d… | 0 | identico |
| Bundesliga | d0799eb7e5f132a2… | d0799eb7e5f132a2… | 0 | identico |
| Ligue 1 | eb1a12151263360f… | eb1a12151263360f… | 0 | identico |

Esito: **VERDE** — il secondo run non produce alcun diff sui CSV (celle riscritte: 0).

### C) Non regressione del bug di dedup

Simulazione della sequenza reale `update_db_rich.py → update_db.py → update_db_rich.py`.
`update_db.py` non è stato eseguito (richiede la chiave API e scriverebbe sui file
di produzione): ne è stata replicata **fedelmente la logica di merge** (righe 143-160:
`pd.concat([df_old, df_new])` + `drop_duplicates(subset=[Date,HomeTeam,AwayTeam],
keep="last")` + ordinamento per data), con `df_new` = le righe API delle stesse
partite (le 10 colonne che l'API espone, stessi nomi squadra: il caso migliore).

| Lega | celle ricche dopo run 1 | celle ricche dopo update_db.py | azzerate | recuperate dal run 3 di update_db_rich |
|---|---|---|---|---|
| Serie A | 4119 | 0 | 4119 | 4119 |
| Premier League | 3950 | 0 | 3950 | 3950 |
| La Liga | 5997 | 0 | 5997 | 5997 |
| Bundesliga | 2881 | 0 | 2881 | 2881 |
| Ligue 1 | 4136 | 0 | 4136 | 4136 |

Esito: **il bug si riproduce**

**Prerequisito per la commessa di integrazione (da riportare, senza modificare
`update_db.py` in questa sede):**

> il merge dentro update_db.py va rifatto per colonna (come in update_db_rich.merge_columns) PRIMA di integrare update_db_rich.py nel workflow: con il concat + drop_duplicates(keep="last") attuale, il primo run di update_db.py dopo l'arricchimento azzera 21083 celle delle colonne ricche (tutte: la riga API ha solo 10 colonne e vince sul duplicato).
> Il terzo run di update_db_rich.py le recupera, ma solo perché riscarica tutto da football-data.co.uk: finché update_db.py non cambia, il dato ricco è garantito solo se update_db_rich.py gira DOPO update_db.py, e comunque la finestra in cui il dato è azzerato resta reale.

### D) Copertura di `B365H` e `HS` (soglia 90%)

| Lega | partite concluse | B365H non nulle | % B365H | HS non nulli | % HS | Esito |
|---|---|---|---|---|---|---|
| Serie A | 40 | 40 | 100.0% | 40 | 100.0% | OK |
| Premier League | 45 | 38 | 84.4% | 38 | 84.4% | SOTTO SOGLIA |
| La Liga | 75 | 58 | 77.3% | 58 | 77.3% | SOTTO SOGLIA |
| Bundesliga | 31 | 28 | 90.3% | 28 | 90.3% | OK |
| Ligue 1 | 40 | 40 | 100.0% | 40 | 100.0% | OK |

Esito complessivo: **ROSSO (sotto soglia: Premier League, La Liga)**. Leghe sotto soglia: Premier League, La Liga.

Motivo per partita non coperta (le due sonde coincidono sempre: le colonne
arrivano dalla stessa riga del CSV):

| Lega | Data | Partita | Motivo |
|---|---|---|---|
| Premier League | 21/08/2026 | Arsenal - Coventry City | nome squadra non allineato: Coventry City non compare fra i nomi del CSV football-data dopo clean_name() |
| Premier League | 22/08/2026 | Hull City - Man United | nome squadra non allineato: Hull City non compare fra i nomi del CSV football-data dopo clean_name() |
| Premier League | 29/08/2026 | Coventry City - Hull City | nome squadra non allineato: Coventry City, Hull City non compare fra i nomi del CSV football-data dopo clean_name() |
| Premier League | 05/09/2026 | Man City - Coventry City | nome squadra non allineato: Coventry City non compare fra i nomi del CSV football-data dopo clean_name() |
| Premier League | 05/09/2026 | Hull City - Aston Villa | nome squadra non allineato: Hull City non compare fra i nomi del CSV football-data dopo clean_name() |
| Premier League | 12/09/2026 | Chelsea - Hull City | nome squadra non allineato: Hull City non compare fra i nomi del CSV football-data dopo clean_name() |
| Premier League | 13/09/2026 | Coventry City - Brighton | nome squadra non allineato: Coventry City non compare fra i nomi del CSV football-data dopo clean_name() |
| La Liga | 17/08/2026 | Deportivo - Elche | nome squadra non allineato: Deportivo non compare fra i nomi del CSV football-data dopo clean_name() |
| La Liga | 19/08/2026 | Atleti - Málaga | nome squadra non allineato: Málaga non compare fra i nomi del CSV football-data dopo clean_name() |
| La Liga | 19/08/2026 | Ath Madrid - Málaga | nome squadra non allineato: Málaga non compare fra i nomi del CSV football-data dopo clean_name() |
| La Liga | 24/08/2026 | Málaga - Deportivo | nome squadra non allineato: Deportivo, Málaga non compare fra i nomi del CSV football-data dopo clean_name() |
| La Liga | 30/08/2026 | Real Madrid - Málaga | nome squadra non allineato: Málaga non compare fra i nomi del CSV football-data dopo clean_name() |
| La Liga | 30/08/2026 | Deportivo - Valencia | nome squadra non allineato: Deportivo non compare fra i nomi del CSV football-data dopo clean_name() |
| La Liga | 05/09/2026 | Villarreal - Deportivo | nome squadra non allineato: Deportivo non compare fra i nomi del CSV football-data dopo clean_name() |
| La Liga | 06/09/2026 | Málaga - Levante | nome squadra non allineato: Málaga non compare fra i nomi del CSV football-data dopo clean_name() |
| La Liga | 13/09/2026 | Celta - Málaga | nome squadra non allineato: Málaga non compare fra i nomi del CSV football-data dopo clean_name() |
| La Liga | 13/09/2026 | Getafe - Deportivo | nome squadra non allineato: Deportivo non compare fra i nomi del CSV football-data dopo clean_name() |
| La Liga | 15/09/2026 | Vallecano - Espanol | partita successiva all'ultimo aggiornamento del CSV (ultima data presente: 14/09/2026) |
| La Liga | 15/09/2026 | Alaves - Valencia | partita successiva all'ultimo aggiornamento del CSV (ultima data presente: 14/09/2026) |
| La Liga | 15/09/2026 | Elche - Real Madrid | partita successiva all'ultimo aggiornamento del CSV (ultima data presente: 14/09/2026) |
| La Liga | 16/09/2026 | Levante - Ath Bilbao | partita successiva all'ultimo aggiornamento del CSV (ultima data presente: 14/09/2026) |
| La Liga | 16/09/2026 | Deportivo - Sevilla | nome squadra non allineato: Deportivo non compare fra i nomi del CSV football-data dopo clean_name() |
| La Liga | 16/09/2026 | Ath Madrid - Osasuna | partita successiva all'ultimo aggiornamento del CSV (ultima data presente: 14/09/2026) |
| La Liga | 16/09/2026 | Barcelona - Santander | partita successiva all'ultimo aggiornamento del CSV (ultima data presente: 14/09/2026) |
| Bundesliga | 29/08/2026 | Mainz - SC Paderborn | nome squadra non allineato: SC Paderborn non compare fra i nomi del CSV football-data dopo clean_name() |
| Bundesliga | 05/09/2026 | SC Paderborn - Freiburg | nome squadra non allineato: SC Paderborn non compare fra i nomi del CSV football-data dopo clean_name() |
| Bundesliga | 12/09/2026 | Dortmund - SC Paderborn | nome squadra non allineato: SC Paderborn non compare fra i nomi del CSV football-data dopo clean_name() |

### E) Test unitari del merge per colonna

- file: `SoccerMath/test_update_db_rich.py`
- comando: `python SoccerMath/test_update_db_rich.py`
- test eseguiti: **34**, esito **VERDE**
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

| Lega | Data | Partita (come nel *_Live.csv) | chiave pulita | motivo |
|---|---|---|---|---|
| Premier League | 21/08/2026 | Arsenal - Coventry City | Arsenal / Coventry City | nome squadra non allineato: Coventry City non compare fra i nomi del CSV football-data dopo clean_name() |
| Premier League | 22/08/2026 | Hull City - Man United | Hull City / Man United | nome squadra non allineato: Hull City non compare fra i nomi del CSV football-data dopo clean_name() |
| Premier League | 29/08/2026 | Coventry City - Hull City | Coventry City / Hull City | nome squadra non allineato: Coventry City, Hull City non compare fra i nomi del CSV football-data dopo clean_name() |
| Premier League | 05/09/2026 | Man City - Coventry City | Man City / Coventry City | nome squadra non allineato: Coventry City non compare fra i nomi del CSV football-data dopo clean_name() |
| Premier League | 05/09/2026 | Hull City - Aston Villa | Hull City / Aston Villa | nome squadra non allineato: Hull City non compare fra i nomi del CSV football-data dopo clean_name() |
| Premier League | 12/09/2026 | Chelsea - Hull City | Chelsea / Hull City | nome squadra non allineato: Hull City non compare fra i nomi del CSV football-data dopo clean_name() |
| Premier League | 13/09/2026 | Coventry City - Brighton | Coventry City / Brighton | nome squadra non allineato: Coventry City non compare fra i nomi del CSV football-data dopo clean_name() |
| La Liga | 17/08/2026 | Deportivo - Elche | Deportivo / Elche | nome squadra non allineato: Deportivo non compare fra i nomi del CSV football-data dopo clean_name() |
| La Liga | 19/08/2026 | Atleti - Málaga | Ath Madrid / Málaga | nome squadra non allineato: Málaga non compare fra i nomi del CSV football-data dopo clean_name() |
| La Liga | 19/08/2026 | Ath Madrid - Málaga | Ath Madrid / Málaga | nome squadra non allineato: Málaga non compare fra i nomi del CSV football-data dopo clean_name() |
| La Liga | 24/08/2026 | Málaga - Deportivo | Málaga / Deportivo | nome squadra non allineato: Deportivo, Málaga non compare fra i nomi del CSV football-data dopo clean_name() |
| La Liga | 30/08/2026 | Real Madrid - Málaga | Real Madrid / Málaga | nome squadra non allineato: Málaga non compare fra i nomi del CSV football-data dopo clean_name() |
| La Liga | 30/08/2026 | Deportivo - Valencia | Deportivo / Valencia | nome squadra non allineato: Deportivo non compare fra i nomi del CSV football-data dopo clean_name() |
| La Liga | 05/09/2026 | Villarreal - Deportivo | Villarreal / Deportivo | nome squadra non allineato: Deportivo non compare fra i nomi del CSV football-data dopo clean_name() |
| La Liga | 06/09/2026 | Málaga - Levante | Málaga / Levante | nome squadra non allineato: Málaga non compare fra i nomi del CSV football-data dopo clean_name() |
| La Liga | 13/09/2026 | Celta - Málaga | Celta / Málaga | nome squadra non allineato: Málaga non compare fra i nomi del CSV football-data dopo clean_name() |
| La Liga | 13/09/2026 | Getafe - Deportivo | Getafe / Deportivo | nome squadra non allineato: Deportivo non compare fra i nomi del CSV football-data dopo clean_name() |
| La Liga | 15/09/2026 | Vallecano - Espanol | Vallecano / Espanol | partita successiva all'ultimo aggiornamento del CSV (ultima data presente: 14/09/2026) |
| La Liga | 15/09/2026 | Alaves - Valencia | Alaves / Valencia | partita successiva all'ultimo aggiornamento del CSV (ultima data presente: 14/09/2026) |
| La Liga | 15/09/2026 | Elche - Real Madrid | Elche / Real Madrid | partita successiva all'ultimo aggiornamento del CSV (ultima data presente: 14/09/2026) |
| La Liga | 16/09/2026 | Levante - Ath Bilbao | Levante / Ath Bilbao | partita successiva all'ultimo aggiornamento del CSV (ultima data presente: 14/09/2026) |
| La Liga | 16/09/2026 | Deportivo - Sevilla | Deportivo / Sevilla | nome squadra non allineato: Deportivo non compare fra i nomi del CSV football-data dopo clean_name() |
| La Liga | 16/09/2026 | Ath Madrid - Osasuna | Ath Madrid / Osasuna | partita successiva all'ultimo aggiornamento del CSV (ultima data presente: 14/09/2026) |
| La Liga | 16/09/2026 | Barcelona - Santander | Barcelona / Santander | partita successiva all'ultimo aggiornamento del CSV (ultima data presente: 14/09/2026) |
| Bundesliga | 29/08/2026 | Mainz - SC Paderborn | Mainz / SC Paderborn | nome squadra non allineato: SC Paderborn non compare fra i nomi del CSV football-data dopo clean_name() |
| Bundesliga | 05/09/2026 | SC Paderborn - Freiburg | SC Paderborn / Freiburg | nome squadra non allineato: SC Paderborn non compare fra i nomi del CSV football-data dopo clean_name() |
| Bundesliga | 12/09/2026 | Dortmund - SC Paderborn | Dortmund / SC Paderborn | nome squadra non allineato: SC Paderborn non compare fra i nomi del CSV football-data dopo clean_name() |

Totale: 27 righe non appaiate su 231 righe complessive.

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

