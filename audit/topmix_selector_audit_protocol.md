# Protocollo di audit del selettore Top Mix

Documento di **progettazione**. Non esegue il confronto, non cerca soglie o
pesi nuovi, non consuma un hold-out tenuto da parte.

I sette mercati restano quelli di produzione: **1, X, 2, Over 2.5, Under 2.5,
GG, NG**. Modello, dati, soglie e pesi del primo confronto sono identici a
`fetch_and_calc_top_mix` in `SoccerMath/app.py`.

---

## 1. Cosa si confronta (solo l'ordine)

**A — selettore attuale (produzione)**

1. Calcola le sette probabilità Poisson a due teste.
2. Sceglie il mercato con **massimo Poisson**.
3. Se il mercato è 1/X/2: `confidence = 0.6 * poisson + 0.4 * elo`.
   Se è O/U o GG/NG: `confidence = poisson` (Elo non esiste su quei mercati).
4. Filtri: `confidence >= 0.55` (1X2) o `>= 0.60` (O/U, GG/NG);
   `abs(poisson - elo) < 0.25` (per O/U e GG/NG il disaccordo è 0 per
   costruzione, perché `elo_prob` resta il fallback uguale a Poisson).
5. Graduatoria globale sulle partite ammesse, taglio a **10**.

**B — alternativa (stessi numeri, ordine invertito)**

1. Per **ogni** mercato calcola la probabilità finale con la stessa
   trasformazione che A applica solo al massimo Poisson (mix 0.6/0.4 sui 1X2;
   Poisson puro su O/U e GG/NG).
2. Applica i **stessi** filtri per mercato.
3. Tra i mercati ammessi della partita, sceglie il **massimo ammissibile**.
4. Stessa selezione di giornata, stessa graduatoria globale, stesso limite 10.

Il primo confronto isola **solo l'effetto dell'ordine**. Qualunque differenza
di mercato o di `prob_val` è attribuibile all'ordine, non a un cambio di
modello. Un esempio sintetico (stesse soglie, non dati live) è in
`audit/test_reconstruct_topmix_match.py::TestSelectorOrderEffect`: A sceglie
Over 2.5 al 70%, B sceglie la vittoria casa al 71,2%.

Implementazione di riferimento, in sola lettura:
`audit/reconstruct_topmix_match.py` (`apply_selector_A`, `apply_selector_B`).
Chiama `get_full_poisson_two_heads` e `predict_elo_probs` di produzione.
Non riscrive il motore.

---

## 2. Cosa deve essere riprodotto oltre al mercato

Ogni run di confronto, per essere un confronto del selettore e non di un
backtest semplificato, deve usare:

| Pezzo | Funzione di produzione | Note |
|---|---|---|
| Prossima giornata | `select_next_matchday_matches` | `now` esplicito; finestra `TOP_MIX_ROUND_WINDOW_DAYS=5` |
| Motore | `get_league_engine` + `get_full_poisson_two_heads` | due teste, shrinkage `PRIOR_MATCHES=6`, forma solo in 1X2 |
| Elo 1X2 | `predict_elo_probs` | home advantage per lega |
| Sette mercati | stesso dict di `fetch_and_calc_top_mix` | niente Over 1.5/3.5, niente 1X/X2 |
| Soglie/pesi | 0.6/0.4, 0.55, 0.60, 0.25 | vietato grid-search in questo protocollo |
| Graduatoria | `sorted(..., key=prob, reverse=True)[:10]` | globale sulle 5 leghe |

**Vietato** sostituire in silenzio il motore live con un Poisson a testa
singola, con medie gol al posto degli xG, o con un Elo da backtest in-app
diverso da `models/elo_engine.py`.

---

## 3. Inventario: quali audit e quali stagioni hanno già scelto modifiche

Non si chiama «test intatto» un periodo già usato per decidere il motore.

| Lavoro | Stagioni | Ruolo effettivo | Ha scelto una modifica? |
|---|---|---|---|
| `audit/soccermath_probability_review.md` + `backtest_experiment*.py` | train 2022/23+2023/24; val 2024/25; test 2025/26; monitor 2026/27 | split dichiarato | no formula; ha inquadrato il piano |
| `audit/diagnose_form_totali.py` | val 2024/25 + test 2025/26, 5 leghe | scelta | **sì**: testa Totali senza forma (`att0_pure`) |
| `audit/diagnose_production_baseline.py` | val 2024/25 + test 2025/26 | scelta architettura | **sì**: Poisson a due teste in produzione |
| `audit/diagnose_elo_ensemble.py` | val 2024/25 + test 2025/26 | conferma pesi 0.6/0.4 | pesi già in produzione, non cambiati dopo |
| `audit/prior_matches_audit.py` | val 2024/25 (scelta k); test 2025/26 (un uso); mon 2026/27 | scelta | **sì**: `PRIOR_MATCHES=6` tenuto (zona 6–10) |
| `audit/diagnose_dixon_coles_rho.py`, `diagnose_lambda_compression.py`, `diagnose_ou_gg.py`, `diagnose_time_decay.py` | 2024/25 e/o 2025/26 | diagnosi, non tutte promosse | DC **non** in produzione |
| PR #8, #9, #10 | — | merge in `main` | due teste; next matchday; shrinkage |

**2026/27** è dichiarato «solo monitoraggio prospettico, mai per validare o
tarare» (`soccermath_probability_review.md` §3 nota permanente). Il campione
è piccolo e già osservato come monitor dello shrinkage.

**Non esiste un test storico non utilizzato.** 2022/23 e 2023/24 sono train.
2024/25 è validation di più interventi. 2025/26 è già stato test una-tantum
dello shrinkage e test delle due teste / forma.

Quindi:

- un replay A vs B su 2024/25+2025/26 è **validation storica già esaminata**,
  non un test intatto;
- la **conferma prospettica** è l'unica via non contaminata: Top Mix 2026/27
  in poi, *dopo* che il tracciamento permette di sapere cosa è stato
  selezionato, con quale motore e su quali dati.

---

## 4. Disegno del confronto (quando si eseguirà)

### 4.1 Validation storica (già esaminata — etichettarla così)

Unità: giornata di campionato per le 5 leghe, poi pool globale e taglio a 10,
come in produzione.

Per ogni giornata *completata*:

1. Cutoff = kickoff della prima partita della giornata (fuso esplicito).
2. Motore point-in-time: CSV con `Date < cutoff`; xG da
   `xg_archive.season_averages(..., cutoff=..., cutoff_policy="previous_day")`.
   Non usare lo snapshot xG *attuale* applicato al 2024/25 (leakage di rosa,
   già segnalato in `production_baseline_comparison.md`).
3. Candidati = partite di quella giornata. Questo **non** è
   `select_next_matchday_matches` sul feed TIMED/SCHEDULED: quell'API non ha
   uno storico di status. L'approssimazione va dichiarata (vedi §6).
4. Applica A e B con le funzioni di produzione, stesse soglie.
5. Dopo il risultato reale, valuta solo le selezioni finite.

### 4.2 Conferma prospettica

Ogni run live di Top Mix (max 10 righe) viene loggato col schema di §5 del
rapporto di audit (identificativo calcolo, origine, versione modello/selettore,
kickoff, mercato, probabilità, posizione, riferimento dati). Si misura A
(produzione) in cieco. B si calcola in parallelo **senza** essere mostrato né
salvato nel registro, finché il protocollo non decide altrimenti.

---

## 5. Metriche (sulle stesse selezioni concluse)

Calcolare **separatamente** per A e per B, e il delta A−B con intervallo.

1. **Probabilità media vs frequenza di successo**
   sulla selezione effettivamente scelta (evento binario del mercato).
2. **Brier e calibrazione** dell'evento selezionato
   (non del 1X2 completo se il mercato era Over 2.5).
   Reliability diagram per bucket; n per bucket obbligatorio.
3. **Copertura**: partite candidate, partite ammesse dai filtri, partite
   entrate nella top 10, partite escluse per giornata/finestra.
4. **Composizione** per mercato e per lega (conteggi, non solo percentuali).
5. **Incertezza con dipendenza**
   - la stessa partita può comparire in più calcoli (ricalcolo Top Mix,
     cache 30 min, Analisi Rapida): non trattare le righe come i.i.d.;
   - cluster per `match_id` e per giornata;
   - se si usano più run sullo stesso matchday, una sola osservazione per
     `(match_id, selector)` oppure un modello ad effetti misti;
   - bootstrap a blocchi (giornata o weekend), non bootstrap i.i.d. delle righe.

**Non interpretare automaticamente un gap di calibrazione come prova
esclusiva di bias da selezione.** Un Over 2.5 al 70% può essere mal calibrato
perché il Poisson dei totali è mal calibrato, *oppure* perché A sceglie
sempre il massimo Poisson e quindi campiona la coda. Per distinguere:

- calibrazione **di tutti e sette i mercati** sulle stesse partite candidate,
  prima di qualsiasi selettore (baseline del modello);
- calibrazione **del solo evento selezionato** da A e da B;
- se la baseline è già scalibrata, il gap del selettore non è prova del bias
  d'ordine; se la baseline è calibrata e A (non B) non lo è, l'ordine è un
  candidato.

---

## 6. Impedimenti reali alla ricostruzione storica

Questi limiti **non** si aggirano con un backtest semplificato.

| Impedimento | Perché blocca un replay bit-identico del Top Mix live |
|---|---|
| Fixture TIMED/SCHEDULED | football-data non conserva lo status al millisecondo del click. Senza snapshot API non si sa quali partite erano «prossima giornata» né i `shortName`. |
| Timestamp del calcolo | `salvato_il` non c'è per i Top Mix non persistiti; la cache 30 min congela `now`. |
| Valori di mercato | `MARKET_VALUES` è statico, non versionato per stagione. Applicarlo al 2022 è leakage (già in `soccermath_probability_review.md` §1.7). |
| xG rivisti | Understat rivede gli xG; l'archivio tiene l'ultimo valore (`xg_archive.py`). Un cutoff esclude le partite del giorno, non le revisioni successive. |
| Forma a 5 sul df multi-anno | Per una neopromossa (Schalke) le «ultime 5» includono il 2023. Un backtest «stagione corrente only» non è il motore live. |
| Duplicati Live.csv | Nomi grezzi diversi della stessa partita (`Schalke` / `Schalke 04`) prima di `clean_name`. |
| Elo non persistito | Si ricalcola dai CSV. Stesso snapshot CSV ⇒ stesso Elo *ora*; non è un dump al click. |
| Registro | Dedup per `match_id` e tipo collassato: non si sa quale selezione Top Mix è stata mostrata (vedi rapporto, sezione 2). |

Un protocollo che ignora questi punti e gira un walk-forward sui CSV con
«max 1X2» **non** è un audit del selettore Top Mix.

---

## 7. Cosa questo protocollo non fa

- Non cerca nuove soglie, pesi, o mercati.
- Non usa 2026/27 come test di taratura.
- Non chiama 2024/25 o 2025/26 «test intatto».
- Non scrive sul registro e non tocca JSONBin.
- Non implementa B in produzione.

Il prossimo intervento minimo è il **tracciamento** (schema nel rapporto),
senza il quale né la validation storica né la conferma prospettica hanno
un oggetto misurabile chiamato «Top Mix».
