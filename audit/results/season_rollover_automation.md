# Sessione 1 — Parte A: automazione del rollover di stagione

*Branch `arena/01a0bb9f-soccermath2-0`, 19/09/2026. Nessuna fusione con la Commessa 1ter (quote/corner).*

Obiettivo: al 1° luglio 2027 l'intera catena (acquisizione xG, dati ricchi PPDA/giocatori,
rollover dei CSV, derivazione medie, MARKET_VALUES, alias) deve passare **da sola**, senza
liste da riscrivere a mano. Sei punti diagnosticati il 17/09, verificati sul codice e sui dati
prima di intervenire, eseguiti in quest'ordine.

## Riepilogo

| # | Fix | Esito | Dove |
|---|-----|-------|------|
| 3 | Confine di stagione unico (mese ≥ 7 vs ≥ 8) | **Luglio**, verificato sul calendario reale; un solo modulo foglia | `season_calendar.py`, `config.py`, `app.py`, `prediction_registry.py`, `season_rollover.py`, `xg_archive.py` |
| 1 | `SEASONS` di `update_all_xg_db.py` derivate dalla data | fatto, con tolleranze di rollover solo per la finestra derivata | `update_all_xg_db.py`, `update_all_ppda_player_db.py`, workflow `xg_verify.yml`, `ppda_player_verify.yml` |
| 2 | `HISTORICAL_SEASONS` calcolate | fatto (`config.historical_seasons`) | `config.py` |
| 3b | `update_xg.py` in pre-stagione | uscita 0, file precedente intatto, `season_not_started`/`season_starting` nel report | `update_xg.py` |
| 5 | 30 righe duplicate nei `*_Live.csv` | rimosse (262 → 232 righe), causa corretta a monte | `season_rollover.py`, `update_db.py`, 4 CSV Live |
| 4 | `MARKET_VALUES` → prior xG derivato dai dati | **valutato walk-forward e NON adottato**: peggiora Brier in TEST (sig.) | `audit/market_prior_xg.py`, `audit/results/market_prior_xg_report.md`, `SoccerMath/market_prior.py` (solo audit) |
| 6 | Simulazione rollover luglio/agosto 2027 | 6 passi verdi sull'intera catena, copia del database reale | `SoccerMath/test_rollover_chain_2027.py` |

Test: suite `SoccerMath/` **360 passed, 1 skipped** (baseline 337) — comando obbligatorio
`pytest SoccerMath/ --ignore=SoccerMath/test_theme_toggle.py -p no:cacheprovider`;
`audit/test_*.py` 355 passed, 4 failed **pre-esistenti** (identici con le modifiche accantonate:
3 in `test_reconstruct_topmix_match.py` richiedono la storia git, assente nel clone shallow a un
solo commit; 1 in `test_prediction_registry_date_sorting.py` cerca una stringa `sort_values(...)`
non piu' presente nel blocco Registro di `app.py`). Non toccati: fuori perimetro.

---

## Fix 3 — confine di stagione: luglio o agosto?

**Situazione trovata.** Due regole convivevano: `config.get_current_season_start_year`,
`season_rollover._season_of`, `xg_archive.season_point_in_time_averages` usavano `mese >= 7`;
`app.calcola_stagione_calcolo` e `prediction_registry.season_from_entry` usavano `mese >= 8`.
Una previsione registrata il 15 luglio 2027 sarebbe finita nella stagione 2026/2027 per il
Registro e nella 2027/2028 per il rollover.

**Verifica sul calendario reale (non assunta).** Su tutte le partite delle 5 leghe presenti negli
archivi Understat e nei CSV — 8.834 partite, stagioni 2022/23 → 2026/27 con il calendario
2026/27 completo:

- primo calcio d'inizio di stagione **mai prima del 5 agosto** (2022/23: Bundesliga, Premier
  League, Ligue 1, stagione compressa dal Mondiale invernale); ultimo **mai dopo il 4 giugno**
  (2022/23: La Liga, Serie A);
- **zero partite a luglio**: le due regole classificano in modo identico il 100% delle partite
  reali e coincidono con l'etichetta `season` di Understat (test
  `test_calendario_reale_nessuna_partita_a_luglio`);
- la scelta si gioca quindi sui margini: il 1° luglio dista 27 giorni dall'ultima finale e 35 dal
  primo kickoff osservato; il 1° agosto disterebbe 4 giorni dal primo kickoff (5/8) — un
  calendario anticipato di una settimana lo farebbe fallire;
- e' la convenzione della fonte dati (`soccerdata.Understat.read_seasons`:
  `season_id = year if month >= 7 else year - 1`), quindi la finestra soccerdata e la stagione
  corrente dell'app scattano lo stesso giorno;
- limite dichiarato: nel 2019/20 (pandemia) PL e La Liga finirono a luglio e la Serie A il 2
  agosto; nessuna regola a mese intero copre quel caso (la Serie A cadrebbe fuori anche con
  agosto). Fuori perimetro dati, anomalia nota.

**Scelta: 1° luglio**, definita una volta sola in `SoccerMath/season_calendar.py` (modulo foglia
senza import di progetto, come `team_aliases`, cosi' anche `prediction_registry` — che per
contratto non dipende da Streamlit/pandas/app — puo' importarlo). Tutti e cinque i punti usano
ora la stessa funzione; il test `TestCoerenzaFraModuli` fissa l'identita' su 30/06, 01/07, 15/07,
01/08, 15/08, 24/05.

## Fix 1 e 2 — finestre derivate dalla data

- `season_calendar.season_window(current, 5)` e' l'unica definizione della finestra (stagione
  corrente + 4 precedenti). `config.HISTORICAL_SEASONS = historical_seasons()` (oggi
  `["2025/2026", "2024/2025", "2023/2024", "2022/2023"]`, identico alla lista che era scritta a
  mano); `update_all_xg_db.SEASONS = derive_seasons()` (oggi `2223 2324 2425 2526 2627`,
  identico) e `update_all_ppda_player_db.SEASONS` importa la stessa funzione.
- `--seasons` nei due script e nei workflow ora ha default **vuoto** = finestra derivata;
  passarlo esplicitamente mantiene i controlli rigorosi di prima.
- Al rollover due variazioni sono fisiologiche e, **solo con la finestra derivata**, non bloccano:
  - la stagione piu' vecchia esce (`seasons_aged_out`): ammesso solo per stagioni PIU' VECCHIE
    della finestra; una stagione dentro la finestra che sparisce resta bloccante (test di
    regressione in `test_3_acquisizione_xg_finestra_mobile_luglio_e_agosto`);
  - la stagione nuova non e' ancora su Understat (`season_not_started`): `read_seasons` la
    espone in `getStatData` solo dopo le prime partite giocate, quindi a luglio la 2728
    semplicemente non arriva. Ammesso solo se **nemmeno la baseline** la conteneva; se la
    baseline l'aveva e' una regressione e blocca come prima.
- `update_league(fetcher=None)` risolve `fetch_league` a runtime: il monkeypatch dei test e'
  ora efficace (prima `test_main_returns_nonzero_on_failure` passava solo perche' tentava la
  rete e falliva).

## Fix 3b — `update_xg.py` in pre-stagione

Il workflow `update_xg.yml` (mar/ven) deriva le medie per `CURRENT_SEASON_START_YEAR`: dal 1°
luglio e' la stagione nuova, vuota, e `MIN_TEAMS=10` faceva uscire lo script con 1 (job rosso,
nessun commit) fino alla prima giornata. Ora, se le partite **giocate ed entro il cutoff** della
stagione richiesta sono meno di `min_teams`, la lega e' saltata con uscita 0
(`season_not_started` se 0, `season_starting` se 1-9 — il venerdi' di apertura) e il file della
stagione precedente resta valido. Il conteggio usa le partite giocate, non quelle in calendario
(`played_before_cutoff`): fixture pubblicate ma non giocate = pre-stagione. Con ≥ 10 partite
giocate e ancora < 10 squadre valide (xG assenti) l'errore resta bloccante. Verificato sui dati
reali con cutoff 01/08/2026, 16/08/2026 (2 partite → `season_starting`) e 25/08/2026 (scrive).

## Fix 5 — 30 duplicati nei Live

**Diagnosi confermata sui dati:** 30 righe doppie dopo `clean_name` (0 sulle chiavi grezze):
Premier 5 (Nottingham/Nott'm Forest, Brighton Hove/Brighton, Leeds United/Leeds), La Liga 17
(Alavés/Alaves, Rayo Vallecano/Vallecano, Espanyol/Espanol, Atleti/Ath Madrid, Real
Sociedad/Sociedad, Athletic/Ath Bilbao, Barça/Barcelona), Bundesliga 4 (HSV/Hamburg,
Frankfurt/Ein Frankfurt, Schalke/Schalke 04, Bremen/Werder Bremen), Ligue 1 4 (Olympique
Lyon/Lyon, Stade Rennais/Rennes), Serie A 0. In ogni coppia la riga precedente ha il nome grezzo
dell'API e la successiva il canonico, con Date/punteggio/FTR/giornata identici: la deduplica
`keep='last'` sulla chiave normalizzata non perde nulla. Gli archivi `*_2022..2025.csv` sono
puliti (0 doppioni). "Málaga" e' il nome canonico (Understat "Malaga" → "Málaga",
`MARKET_VALUES["Málaga"]`), non un residuo.

**Causa a monte:** `update_db.py` (merge) e `season_rollover.py` (`DEDUP_KEYS`) deduplicavano
sui nomi GREZZI; quando l'API cambiava grafia la stessa partita entrava due volte. Ora
`season_rollover.normalize_team_columns` + `dedup_matches` (nomi canonici, poi
Date+Home+Away) e' usata da entrambi; il rollover pulisce il Live anche quando non c'e' nulla da
archiviare (stato `cleaned`, idempotente) e nella fusione con un archivio esistente confronta le
chiavi normalizzate senza riscrivere le righe gia' archiviate con i nomi football-data.

**Pulizia una tantum** eseguita dal rollover stesso: 262 → 232 righe (−30 esatte), seconda
esecuzione senza modifiche, 0 doppioni residui, 0 nomi non canonici (4 righe "Köln" → "Koln",
canonico di MARKET_VALUES e xG).

## Fix 4 — MARKET_VALUES: prior xG valutato e NON adottato

Protocollo: `audit/market_prior_xg.py` riproduce **bit-identico** (verificato) il walker
dell'audit 11/09 (`market_values_versioned.py`: testa NORM-SUM + Elo 0.6/0.4, VALIDATION 2024/25,
TEST 2025/26, bootstrap appaiato 2000 resample seed 20260905, Brier/LogLoss/ROI B365) e aggiunge
la variante XGP nella stessa passata. Prior pre-registrato (`SoccerMath/market_prior.py`):
`q = (10·0.65·xGD_prev + n_cur·xGD_cur)/(10 + n_cur)`, `factor = clip(1 + 0.25·q, 0.85, 1.25)`,
promosse = media delle retrocesse, point-in-time (kickoff nel giorno precedente). Copertura
nomi archivio ↔ CSV 100% in tutte le leghe/stagioni.

| aggregato 5 leghe | Brier static | Brier xgp | Δ xgp−static (CI 95%) | ROI B365 Δ |
|---|---:|---:|---|---|
| VALIDATION 2024/25 | 0.6398 | 0.6398 | −0.0000 [−0.0031; +0.0032] n.s. | +2.89 pp n.s. |
| TEST 2025/26 | 0.6335 | 0.6377 | **+0.0042 [+0.0011; +0.0075] sig.** | +0.10 pp n.s. |

Per lega: nessuna lega migliora significativamente; LogLoss peggiora sig. in Premier (T), La Liga
(V), Bundesliga (T). Su 27 configurazioni della griglia (persistence × prior_matches × slope)
**nessuna** batte la tabella in TEST: il verdetto non dipende dai parametri. Lettura: lo xGD della
stagione precedente non vede i cambi di rosa del mercato estivo, che il valore di rosa incorpora;
con ~10 partite converge sullo xGD corrente, gia' rappresentato da forma e snapshot xG.

**Decisione (regola pre-registrata, come da istruzione): si tiene `config.MARKET_VALUES`.**
`market_prior.py` resta come strumento di audit, non collegato all'app. Per il rollover la
tabella non blocca nulla (squadre assenti → default 50, fattore 0.925) e `season_rollover.py` ora
**segnala** le squadre del Live prive di voce, cosi' l'aggiornamento estivo e' un avviso esplicito.
Nota: i valori assoluti differiscono dal referto 11/09 (STATIC V 0.6522 → 0.6398) perche' il
protocollo usa lo snapshot xG corrente come forza primaria; i confronti appaiati restano validi.

## Fix 6 — simulazione esplicita del rollover 2027

`SoccerMath/test_rollover_chain_2027.py`, su copia temporanea del database reale, fetcher finti
(nessuna rete):

1. **config** con data 2027 (`M4_CURRENT_SEASON_START_YEAR=2027` in sottoprocesso, come il
   runner il 1° luglio): `CURRENT_SEASON = 2027/2028`, `HISTORICAL_SEASONS = [2026/2027 …
   2023/2024]`, `SEASONS = 2324 2425 2526 2627 2728` in entrambi gli script; senza override il
   30/06/2027 e' ancora 2026 e il 01/07/2027 scatta 2027.
2. **rollover** al 15/07/2027: i 5 Live 2026/27 diventano `_2026.csv` (0 doppioni, tutte le
   date nella 2026/27), i Live ripartono vuoti con intestazione, seconda esecuzione byte-identica.
3. **acquisizione xG** luglio (Understat senza 2728, 2223 fuori finestra): scritta,
   `season_not_started=2027`, `seasons_aged_out=[2022]`; stesso scenario con `--seasons`
   esplicito → bloccato ("stagioni assenti"); agosto con la prima giornata → scritta; 2728
   presente in baseline e poi assente → bloccato; `main()` senza `--seasons` usa la finestra
   derivata.
4. **derivazione medie** stagione 2027: uscita 0 e file intatto (nessuna partita; fixture
   pubblicate non giocate); prima giornata giocata → file scritto (≥ 10 squadre); una sola
   partita → `season_starting`, non errore.
5. **PPDA/giocatori**: stesse tolleranze di finestra mobile (pre-stagione e stagione uscita),
   `--seasons` default `None`.
6. **MARKET_VALUES/alias**: una neopromossa sconosciuta viene segnalata e non blocca (fattore
   0.925); ogni voce della tabella e' raggiungibile dal nome canonico di `clean_name` e i canonici
   sono punti fissi.

## Post-referto (20/09/2026) — la tolleranza pre-stagione ha una scadenza

Revisione pre-merge delle condizioni esatte con cui la catena tollera l'assenza della
stagione nuova. Entrambe le tolleranze erano **senza limite temporale**: in entrambi i
casi esisteva uno scenario concreto in cui avrebbero nascosto un guasto reale.

**Condizioni prima della correzione.**

1. *Acquisizione* (`update_all_xg_db.update_league`, `rolling_window=True`):
   ```python
   if new_counts.get(current, 0) == 0 and old_counts.get(current, 0) == 0:
       must_have.remove(current)   # tollerata: pre-stagione
   ```
2. *Derivazione* (`update_xg.derive_league`):
   ```python
   played = matches_in_season - sum(skipped[k] for k in _NOT_YET_PLAYABLE)
   if played < min_teams:         # pre-stagione: exit 0, file intatto
   ```

**Il caso che nascondevano (concreto).** Un download rotto ad agosto — Understat che
cambia markup e soccerdata restituisce zero righe per la stagione nuova invece di
sollevare un errore — soddisfa la condizione 1 in modo "innocente" la prima volta; ma la
tolleranza **si auto-alimenta**: l'archivio viene riscritto senza la stagione nuova, la
baseline della corsa successiva non l'avrà e ogni esecuzione continuerà a "tollerare"
fino a maggio, con il workflow verde e l'app che prevede sui dati della stagione prima.
La condizione 2 ha lo stesso buco a valle: stagione assente dall'archivio → 0 partite →
"non ancora iniziata" per sempre (e con un cutoff, anche partite con date illeggibili o
un cutoff sbagliato finivano nello stesso sacco `_NOT_YET_PLAYABLE`). La corruzione
totale delle date è comunque intercettata prima da `validate_archive` ("record con data
illeggibile"); il caso residuo è la stagione mancante/parziale.

**Correzione: termine della tolleranza = 15 settembre** dell'anno di inizio stagione,
unica definizione in `season_calendar.pre_season_deadline` /
`within_pre_season_tolerance` (confronto a livello di data; per la derivazione l'istante
di riferimento è il cutoff, oppure "adesso" se non è dato). Valore scelto sui dati, non
per assunzione: su tutte le 25 combinazioni lega × stagione 2022/23→2026/27 (calendari
completi, incluso il post-Mondiale 2026/27) il primo kickoff più tardivo è stato il
**28/08/2026** (Bundesliga) e al 15/9 ogni lega aveva **≥ 27 partite giocate** contro le
10 richieste: un 15/9 con meno di 10 partite non è mai successo. Se accadrà sarà un
calendario eccezionale e dovrà comunque passare da una verifica manuale, non da una
tolleranza silenziosa.

Dove scatta ora il blocco (tutti verificati su copie dei dati reali):

- `update_all_xg_db.update_league`: assente ovunque **e** oltre il 15/9 → errore
  esplicito ("stagione corrente … assente dal download oltre il 2025-09-15…"), archivio
  intatto; in finestra (luglio-agosto) la tolleranza resta identica a prima.
- `update_all_ppda_player_db`: `_rolling_window_adjustments` non toglie più la stagione
  ma espone `season_late_absent`, e `acquire_league` la trasforma in errore bloccante.
- `update_xg.derive_league`: `played < min_teams` oltre il 15/9 → errore esplicito con
  la diagnosi (date illeggibili / cutoff errato / stagione mai acquisita); entro il 15/9
  resta `pre_season` con uscita 0 e file intatto.

Verifica di non-regressione sul percorso di produzione di oggi: `update_xg.py --dry-run`
sui dati reali → 5/5 leghe, exit 0 (la 2026/27 è in archivio, la tolleranza non è mai
invochiata). La simulazione 2027 (passi 3-5) è invariata perché luglio/agosto 2027 sono
entro il termine. Suite: SoccerMath 367 passed / 1 skipped (7 test nuovi: scadenza del
calendario, casi nascosto/tollerato della derivazione, 3b acquisizione, PPDA); audit
355 passed con i soli 4 fallimenti pre-esistenti.

## File toccati

- Nuovi: `SoccerMath/season_calendar.py`, `SoccerMath/market_prior.py` (audit),
  `SoccerMath/test_season_calendar.py`, `SoccerMath/test_rollover_chain_2027.py`,
  `SoccerMath/test_market_prior.py`, `audit/market_prior_xg.py`,
  `audit/results/market_prior_xg_report.md` (+ `_detail.json`), questo referto.
- Modificati: `config.py`, `app.py` (solo `calcola_stagione_calcolo` + import),
  `prediction_registry.py`, `season_rollover.py`, `update_db.py`, `update_xg.py`,
  `xg_archive.py` (una riga), `update_all_xg_db.py`, `update_all_ppda_player_db.py`,
  `test_rollover.py`, workflow `xg_verify.yml` e `ppda_player_verify.yml`, 4 CSV Live (−30 righe).
- Non toccati: `MARKET_VALUES`, modelli, teste 1X2/Totali, fixture bit-identity, Commessa 1ter.
