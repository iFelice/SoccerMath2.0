# Referto di audit — 2026-10-10 (sola lettura)

Branch `arena/dba6c5ab-soccermath2-0`, base `origin/main` = `2cfaf90`.

Vincoli rispettati: nessuna modifica a `SoccerMath/` né a `app.py`; nessun `--write`; nessuna scrittura nel Registro; nessuna chiave The Odds API in output, log o file (la sonda salva `apiKey=***`). Il replay è stato eseguito con output in `/tmp/replay/`, senza sovrascrivere referti versionati.

Dettagli per tabella: `audit/results/griglia_varianti.md` (punti 2–6), `audit/results/totals_probe_per_lega.md` e `audit/results/totals_probe_analysis.md` (punto 1), `audit/results/griglia_penaltyblog_check.md` (verifica penaltyblog).

---

## 0. Regole dichiarate (scritte prima dei numeri)

- **Punto 1 (sonda totals).** Totals entra in produzione solo se almeno l'85 % degli eventi ha la linea 2,5 da Pinnacle oppure da almeno 3 bookmaker.
- **Punto 3 (scelta della variante ρ).** Metrica: Brier binario per partita sul mercato Gol (No Gol identico). d = Brier(X) − Brier(Y); d < 0 ⇒ X migliore. Bootstrap a blocchi lega × stagione × data, 2000 repliche, seme 20261010, IC 95 % percentile. Passo 1: adottare A solo se l'IC 95 % di A − B è interamente sotto zero; altrimenti passo 2: adottare B solo se l'IC 95 % di B − C è interamente sotto zero; altrimenti C. Il sottocampione Pinnacle applica la stessa procedura come sensibilità e non decide.
- **Punto 4 (calibrazione).** Per ogni coppia evento/complemento si valuta l'esito con p più alta (p ≥ 0,5). Fasce di p: [0,55-0,65), [0,65-0,75), ≥ 0,75. IC 95 % di f − p con bootstrap a blocchi, 2000 repliche, seme 20261011. Un mercato entra nella lista se in *ogni* fascia con n ≥ 100 l'IC di f − p contiene zero **oppure** |f − p| ≤ 3 punti. Se nessuna fascia ha n ≥ 100, il mercato è «non valutabile» e resta fuori.

Le regole sono nel codice (`audit/griglia_varianti.py`, docstring e costante `TOL_PT = 0,03`) e nel referto generato. Dopo il primo run numerico sono state corrette solo correzioni tecniche, documentate al punto 8.

---

## 1. Sonda totals (The Odds API, mercato totals)

Esito: **sonda eseguita** (`audit/data/totals_probe/` contiene 5 risposte grezze, una per lega; nessuna simulazione).

| lega | crediti usati (cumulativi) | residui | eventi | con Pinnacle | Pinnacle 2,5 | Pinnacle altra intera/mezza | Pinnacle asiatica | 2,5 da ≥3 libri | quota regola |
|---|---|---|---|---|---|---|---|---|---|
| Premier League | 60 | 440 | 17 | 15 | 4 | 7 | 4 | 13 | 76,5 % |
| Ligue 1 | 63 | 437 | 17 | 17 | 3 | 5 | 9 | 13 | 76,5 % |
| Bundesliga | 62 | 438 | 12 | 12 | 0 | 8 | 4 | 2 | 16,7 % |
| Serie A | 59 | 441 | 19 | 19 | 4 | 4 | 11 | 16 | 84,2 % |
| La Liga | 61 | 439 | 17 | 17 | 3 | 2 | 12 | 12 | 70,6 % |
| **Totale** | **63 (stato finale)** | **437 (stato finale)** | **82** | **80** | **14** | **26** | **40** | **56** | **68,3 %** |

- Crediti: una chiamata per lega (1 credito ciascuna), 5 crediti spesi nel run. Stato finale da `_summary.json`: usati 63, residui 437.
- **Errore segnalato:** `audit/results/totals_probe_analysis.md` riporta 61/439, cioè lo stato dell'ultima lega in ordine alfabetico, non lo stato finale. Non l'ho corretto nello script; il dato corretto è quello qui sopra.
- Linee Pinnacle: «2,5» indica la linea 2,5 esatta; «altra intera/mezza» indica linee x,0 o x,5 diverse da 2,5; «asiatica» indica quarti x,25 o x,75. Nessun evento ha solo linee asiatiche; nessun libro ha linee multiple nello stesso evento.

**Esito della regola (≥ 85 %): NON superata.** 56 eventi su 82 = 68,3 %. Totals **non** va in produzione. Nessuna azione sul codice di produzione.

---

## 2. Convenzione tau: produzione, Dixon & Coles (1997), penaltyblog

Formula di riferimento: arXiv:2103.07272 (Petretta et al., 2022), eq. (2), attribuita a Dixon & Coles (1997), con x = gol casa, λ = media casa, μ = media trasferta:

- τ(0,0) = 1 − λμρ
- τ(0,1) = 1 + λρ
- τ(1,0) = 1 + μρ
- τ(1,1) = 1 − ρ
- altrimenti τ = 1

Fonte primaria (Dixon & Coles 1997, *JRSS C*) non accessibile: paywall OUP e il PDF su `web.math.ku.dk` restituisce 404. Il riferimento è quindi l'eq. (2) dell'articolo citato, con concordanza di tre fonti secondarie.

Esempio numerico: λ = 1,0, μ = 1,5, ρ = −0,10.

| cella (x casa, y trasferta) | produzione `tau_correction` (`SoccerMath/models/dixon_coles.py`, righe 32–47) | Dixon & Coles 1997 (eq. 2) | penaltyblog 1.13.1 (sorgente, `football_probability_grid.py`, righe ~536–541) |
|---|---|---|---|
| (0,0) | 1,1500 | 1,1500 | 1,1500 |
| (0,1) | 0,9000 | 0,9000 | 0,8500 |
| (1,0) | 0,8500 | 0,8500 | 0,9000 |
| (1,1) | 1,1000 | 1,1000 | 1,1000 |

**Conclusione:** la produzione coincide con l'articolo cella per cella. Penaltyblog applica 1+ρλ alla cella (1,0) e 1+ρμ alla cella (0,1): le due celle sono scambiate rispetto alla formula, cioè un'indicizzazione opposta. **La produzione non è invertita: nessuna correzione.**

Per quantificare la differenza che la convenzione penaltyblog produrrebbe sui derivati (scenario **non** in produzione, parametri per partita della variante A): massimo |Δ probabilità| 0,025 su 1X+Under 3,5; mediana |Δ| ≤ 0,003 su tutti i derivati (dettaglio in `griglia_varianti.md` §2).

---

## 3. ρ per partita e varianti (campione PR #58: 3504 partite; sensibilità Pinnacle 2623)

Varianti: **A** DC con ρ per partita. **B** DC con ρ fisso = mediana dei ρ impliciti 2024/25 (−0,0811) applicata a 2025/26, con λ e μ rifittati per partita; per 2024/25, ρ = 0 (dichiarato). **C** Poisson indipendente (ρ = 0).

**Distribuzione di ρ in A** (campione principale): p1 −0,181 · p5 −0,146 · p25 −0,106 · **p50 −0,078** · p75 −0,048 · p95 +0,020 · p99 +0,090.

**Quota di partite al bordo** (|ρ| ≥ 0,49 con limiti ±0,5): **0,00 %**. Partite con clip τ attivo: 0,00 %.

**Brier appaiato su Gol (regola R3):**

| campione | confronto | ΔBrier (X − Y) | IC 95 % a blocchi | esito |
|---|---|---|---|---|
| principale (3504) | A − B | −0,00039 | [−0,00076; −0,00004] | A migliore (IC < 0) |
| principale (3504) | B − C | −0,00026 | [−0,00055; +0,00004] | nessuna differenza dimostrata |
| Pinnacle (2623) | A − B | −0,00065 | [−0,00119; −0,00011] | A migliore (IC < 0) |
| Pinnacle (2623) | B − C | −0,00011 | [−0,00046; +0,00023] | nessuna differenza dimostrata |

**Decisione R3: variante A** (campione principale e sensibilità Pinnacle concordi). Il Brier di A è migliore di B di circa 0,0004 (unità di Brier); l'effetto è piccolo, ma l'IC è interamente sotto zero.

**Derivati (ΔBrier A − B e A − C, media [IC 95 %]):**

| evento | A − B | A − C |
|---|---|---|
| Gol | −0,00039 [−0,00076; −0,00004] | −0,00065 [−0,00112; −0,00019] |
| Over 1,5 | −0,00010 [−0,00041; +0,00021] | −0,00015 [−0,00055; +0,00027] |
| Over 3,5 | 0,00000 [−0,00013; +0,00013] | +0,00003 [−0,00013; +0,00019] |
| 1X | +0,00012 [−0,00014; +0,00036] | −0,00000 [−0,00031; +0,00030] |
| X2 | −0,00021 [−0,00041; −0,00000] | −0,00027 [−0,00052; −0,00001] |
| 12 | −0,00014 [−0,00060; +0,00029] | −0,00036 [−0,00092; +0,00019] |
| 1+Over 1,5 | +0,00009 [−0,00002; +0,00020] | +0,00007 [−0,00007; +0,00021] |
| 2+Over 1,5 | −0,00004 [−0,00012; +0,00004] | −0,00001 [−0,00011; +0,00008] |
| 1X+Over 1,5 | +0,00011 [−0,00024; +0,00044] | −0,00007 [−0,00052; +0,00038] |
| 1X+Under 3,5 | +0,00009 [−0,00007; +0,00024] | +0,00006 [−0,00014; +0,00025] |
| X2+Under 3,5 (extra, in PR #58) | −0,00006 [−0,00021; +0,00009] | −0,00010 [−0,00029; +0,00009] |

---

## 4. Calibrazione assoluta dei derivati, variante A

Fasce [0,55-0,65), [0,65-0,75), ≥ 0,75. Tabelle complete con n, p media, frequenza f, f − p e IC 95 %: `audit/results/griglia_varianti.md` §4.

| mercato (esito più probabile) | fasce con n ≥ 100 | esito R4 |
|---|---|---|
| Gol | 0,55-0,65 n=1661 (f−p −0,0 pt); 0,65-0,75 n=126 (−3,9 pt, IC [−12,6; +5,1]) | **entra** |
| Over 1,5 | n=146 / 1134 / 2222; f−p −1,2 / −0,0 / +0,2 pt | **entra** |
| Over 3,5 | n=802 / 1593 / 894; f−p +0,1 / −0,0 / +1,9 pt (IC ≥0,75 [−0,8; +4,5]) | **entra** |
| 1X | n=775 / 938 / 1443; f−p −1,5 / +0,7 / +1,1 pt | **entra** |
| 12 | fascia 0,55-0,65 n=2 (non valutabile); 0,65-0,75 n=2039 (−0,9 pt); ≥0,75 n=1463 (+0,4 pt) | **entra** |
| 2+Over 1,5 | n=482 / 669 / 2116; f−p +0,3 / −1,1 / −0,0 pt | **entra** |
| 1X+Under 3,5 | n=1633 / 430 / 122; f−p +1,8 / +3,1 / +3,8 pt (IC contengono zero) | **entra** |
| X2 | fasce 0,65-0,75 f−p +3,2 pt, IC [+0,2; +5,9]; ≥0,75 f−p +4,0 pt, IC [+1,5; +6,5] | non calibrato |
| 1+Over 1,5 | 0,65-0,75 f−p +3,0 pt, IC [+0,4; +5,9]; ≥0,75 +2,7 pt, IC [+0,5; +4,7] | non calibrato |
| 1X+Over 1,5 | ≥0,75 n=368: f−p +4,5 pt, IC [+0,8; +8,2] | non calibrato |
| X2+Under 3,5 (extra) | 0,55-0,65 / 0,65-0,75 / ≥0,75: n = 1355 / 666 / 451; tutti IC contenenti zero o ≤ 3 pt | calibrato (extra, non nell'elenco del brief) |

**Lista delle giocate (R4, elenco del brief): Gol, Over 1,5, Over 3,5, 1X, 12, 2+Over 1,5, 1X+Under 3,5.** X2, 1+Over 1,5 e 1X+Over 1,5 sono fuori: il loro f−p supera 3 punti con IC che esclude lo zero. Nota: i mercati derivano tutti dalla stessa griglia per partita, quindi non sono indipendenti; la calibrazione misura la griglia, non una quota diretta.

---

## 5. Fascia alta 1X2 (p ≥ 0,65), IC 95 %

Campione principale B365 (3504 partite) e sottocampione Pinnacle/B365 (2623). Dettaglio completo in `griglia_varianti.md` §5.

| campione / bookmaker | de-vig | esito | n | p media | f | f − p [IC 95 %] |
|---|---|---|---|---|---|---|
| B365 (3504) | proporzionale | 1 | 500 | 72,92 % | 77,80 % | **+4,9 pt [+1,2; +8,6]** |
| B365 (3504) | proporzionale | 2 | 122 | 70,65 % | 76,23 % | **+5,6 pt [−2,2; +12,7]** |
| B365 (3504) | Shin | 1 | 547 | 73,82 % | 75,69 % | +1,9 pt [−1,7; +5,5] |
| B365 (3504) | Shin | 2 | 129 | 71,87 % | 75,97 % | +4,1 pt [−3,3; +11,1] |
| B365 (3504) | potenza | 1 | 571 | 74,28 % | 75,31 % | +1,0 pt [−2,4; +4,7] |
| B365 (3504) | potenza | 2 | 136 | 72,28 % | 76,47 % | +4,2 pt [−3,3; +11,2] |
| B365 (2623) | proporzionale | 1 | 369 | 72,30 % | 78,59 % | +6,3 pt [+2,0; +10,6] |
| B365 (2623) | Shin | 1 | 405 | 73,20 % | 76,05 % | +2,9 pt [−1,4; +7,0] |
| B365 (2623) | potenza | 1 | 420 | 73,71 % | 75,48 % | +1,8 pt [−2,4; +6,0] |
| Pinnacle (2623) | proporzionale | 1 | 386 | 73,29 % | 77,72 % | +4,4 pt [+0,1; +8,7] |
| Pinnacle (2623) | proporzionale | 2 | 100 | 71,36 % | 73,00 % | +1,6 pt [−7,3; +9,7] |

**Lettura.** Il +5 pt sull'esito 1 (n = 500) è significativo solo con il de-vig proporzionale (IC [+1,2; +8,6]). Con Shin scende a +1,9 pt e con potenza a +1,0 pt, entrambi con IC che contiene zero. Il +6 pt sull'esito 2 (n = 122) ha IC che contiene zero con ogni metodo. Sullo stesso sottocampione 2623, B365 proporzionale dà +6,3 pt contro +4,4 pt di Pinnacle proporzionale: il bookmaker conta, ma poco. Il metodo conta di più: per B365 2623 il passaggio da proporzionale a Shin riduce lo scarto da +6,3 a +2,9 pt. **Lo scarto dipende principalmente dal metodo di de-vig** (il proporzionale attribuisce il margine in modo uniforme e quindi sottostima la probabilità dei favoriti), in secondo luogo dal bookmaker. Nessuna modifica alla produzione.

---

## 6. Stima della quota bet365 (fit 2024/25, test 2025/26): coda dell'errore

Modello della PR #58: quota bet365 stimata da quota equa Pinnacle di apertura, per lega × tipo × fascia di quota equa. Fasce per **quota reale** bet365. Errore relativo |q̂/q − 1| ed errore assoluto |q̂ − q| in punti di quota.

| fascia di quota reale | n | errore rel. mediano | P90 | P99 | errore assoluto mediano | P90 | P99 |
|---|---|---|---|---|---|---|---|
| 1,20-1,50 | 232 | 0,95 % | 2,50 % | 4,70 % | 0,013 | 0,034 | 0,060 |
| 1,50-2,00 | 1250 | 0,91 % | 2,26 % | 3,54 % | 0,015 | 0,039 | 0,066 |
| 2,00-3,00 | 1287 | 1,30 % | 3,01 % | 5,68 % | 0,030 | 0,070 | 0,140 |
| oltre 3,00 | 1704 | 2,23 % | 6,66 % | 16,96 % | 0,086 | 0,361 | 1,872 |
| tutte | 4490 | 1,36 % | 4,09 % | 12,55 % | 0,032 | 0,163 | 1,043 |

Controllo di parità con PR #58: mediana 1,36 % e P90 4,09 %, come nel referto PR #58. Fuori dalle quattro fasce (quota < 1,20): 17 osservazioni. La coda è concentrata sopra quota 3,00: P99 16,96 %.

---

## 7. Limiti

- La data è usata come proxy della giornata: il CSV non ha la giornata (come PR #58).
- Le quote B365 sono quelle storiche pre-partita dei CSV (non The Odds API); l'orario di rilevazione non è nel CSV.
- Pinnacle di apertura (PS*) per il punto 6; chiusura (PSC*) per il punto 5 (come PR #58).
- Il 1X+Under 3,5 e gli Over/Under 1,5 e 3,5 non sono quotati nel campione: sono ricavati dalla griglia.
- La calibrazione non dice nulla sul valore economico di una giocata a quota.
- Nessuna variante tocca la produzione.

---

## 8. Correzioni tecniche allo script dopo il primo run numerico

Il primo run numerico è andato in errore in fase di referto (`NameError` su helper mancanti). Sono state fatte solo correzioni tecniche, senza modificare regole o soglie:

1. Helper `fmt`, `pct`, `pts`, `md_table` riaggiunti (persi nella riscrittura).
2. Costante `TOL_PT = 0,03` dichiarata (usata da R4, già prevista dalla regola).
3. Flag della cache invertito in `main` (`get_fits(not args.no_cache, ...)`): il run successivo ha ricalcolato i fit invece di usare la cache.
4. `devig_shin` e `devig_power` restituiscono il proporzionale quando il margine è nullo (Π ≤ 1): caso degenere trovato dal test `test_shin_su_margine_nullo_coincide_con_proporzionale`. Verificato sui dati: nessuna riga ha Π ≤ 1 (Π minimo 1,033 su B365 1X2, 3504 righe; 1,006 su Pinnacle di chiusura, 2650 righe valide). La correzione non cambia i numeri.
5. Presentazione: X2+Under 3,5 spostato fuori dall'elenco delle giocate (era marcato «extra» e non decideva nulla); tabella dell'effetto tau aggiunta alla §2.

Verifica di determinismo: vedi §9.

---

## 9. Verifica dei numeri (controlli)

- Test unitari `audit/test_griglia_varianti.py`: 7 passati (Shin/potenza su somma 1, quote NaN, margine nullo, tau produzione = articolo, penaltyblog scambiata su (0,1)/(1,0), fit a ρ fisso, complementarità P(Gol) + P(No Gol) = 1).
- Parità con PR #58: 1 n = 500 +4,9 pt e 2 n = 122 +5,6 pt; mediana ρ −0,078 e 5°–95° [−0,146; +0,020]; punto 6 mediana 1,36 % e P90 4,09 %.
- Parità del replay con PR #49: 1302 / 1144 / 335, Δn = 0 (vedi chiusura).
- Determinismo: rerun completo con `--no-cache` (fit ricalcolati da zero, 300 s): referto identico salvo il timestamp di generazione e JSON identico (`==`).

---

## 10. Discrepanze da segnalare

- (a) Il brief chiede «1X+Under 3,5»; il referto PR #58 (`griglia_implicita.md`) riporta «X2+Under 3,5». Qui sono calcolati entrambi: 1X+Under 3,5 nella lista, X2+Under 3,5 come extra.
- (b) Le fasce del brief per il punto 4 ([0,55-0,65), [0,65-0,75), ≥ 0,75) sono diverse da quelle di `griglia_implicita.md`. Si usano quelle del brief.
- (c) `totals_probe_analysis.md` riporta lo stato crediti dell'ultima lega (61/439) invece di quello finale (63/437). Non corretto nello script (tracciato in repo).
- (d) La soglia di 0,49 per il bordo ρ è usata come segnalazione: i limiti del fit sono ±0,5.

---

## 11. Elenco non verificato

- Dixon & Coles (1997), fonte primaria: non letta (paywall e 404). La formula è verificata solo sull'eq. (2) di arXiv:2103.07272 e su fonti secondarie concordi.
- Sorgente penaltyblog 1.13.1: letto via `pip download`, non eseguito con i nostri dati.
- Quote B365 e Pinnacle: storico CSV del repo, non verificato contro The Odds API (il piano gratuito non include lo storico).
- Interpretazione della regola R3 al passo 1 («altrimenti B»): letta come B candidata contro A, poi B vs C (dichiarata in §0).
- Interpretazione di R4 per mercati con n < 100 in una fascia: «non valutabile» (dichiarata in §0).
- Log e artifact CI non scaricabili dalla sandbox: esiti verificati solo a livello di step (API). Conteggi del replay in CI non letti; `Replay Top Mix legacy` saltato su questa PR (vedi chiusura).
- Suite completa: eseguita localmente con gli stessi comandi del workflow `test_suite.yml`, non sul runner GitHub.

---

## 12. Chiusura

**Suite completa** (`pytest` su tutti i `test_*.py` tracciati tranne `SoccerMath/test_theme_toggle.py`, più `test_theme_toggle.py` come script): output reale integrale in `audit/results/suite_completa_2026-10-10.log`. Esito: **1866 passed, 4773 subtests passed, exit 0**; `test_theme_toggle.py` exit 0.

**Replay** `topmix_mercato_v3` (`audit/replay_topmix_mercato.py`, senza `--write`, output in `/tmp/replay/`): esito **PARITÀ** con PR #49. Conteggi 1302 / 1144 / 335, Δn = +0 su tutte e tre le voci; hit 0,6751 / 0,6818 / 0,4358. Output reale in `/tmp/replay/stdout.log`; referto in `/tmp/replay/replay_topmix_mercato.md`.

**CI dei tre workflow sulla PR #59, commit `02efd489`** (esiti step per step da `gh api .../actions/runs/<id>/jobs`):

- `Suite test completa` (run 38072503531): **success**. Step: Checkout, Dipendenze, Elenco dei file di test, Suite pytest (tutti i `test_*.py` tracciati), test_theme_toggle.py come script, Riepilogo: tutti **success**.
- `Audit Top Mix` (run 38072503547): **success**. Step: Test diagnostici Top Mix ed Elo, **Replay offline del Top Mix di mercato (topmix_mercato_v3): success**, Ispezione tracciamento Registro, Nessuna modifica ai dati/codice di produzione: tutti **success**.
- `Replay Top Mix legacy` (run 38072503538): **success**, ma **tutti gli step di replay sono `skipped`**: il workflow salta il replay quando la PR non tocca file rilevanti per il replay. Questo run quindi **non esegue** il replay legacy e non è una verifica del replay.

**Limite:** i log testuali (`gh run view --log`, `gh api .../jobs/<id>/logs`) e l'artifact `topmix-audit-38072503547` non sono scaricabili dalla sandbox (errore EOF dal servizio GitHub). I conteggi 1302/1144/335 del replay in CI non sono quindi leggibili qui. Sono verificati in locale con lo stesso script (`audit/replay_topmix_mercato.py`, output in `/tmp/replay/`).
