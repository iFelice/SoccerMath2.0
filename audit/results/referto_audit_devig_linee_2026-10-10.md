# Referto di audit — de-vig per la produzione, calibrazione dei derivati, diagnosi sonda totals, fit su linea totals qualunque

Data: 2026-10-10 · branch `arena/2ea4e1ff-soccermath2-0` · base `origin/main` = `a163a35` (PR #59 mergiata).

Vincoli di questo audit: **nessuna modifica a `SoccerMath/` né a `app.py`**, nessun replay con `--write`,
nessuna scrittura nel Registro, **nessuna nuova chiamata a The Odds API** (tutte le analisi leggono file già
presenti nel repository), nessuna chiave The Odds API in output, log o file.

Script nuovi (in `audit/`): `devig_produzione.py` (punto 1), `griglia_devig.py` (punto 2),
`totals_probe_diagnosi.py` (punto 3), `linee_totali_probe.py` (punto 4),
`test_griglia_core_linee.py` e `test_totals_probe_diagnosi.py` (test).
Modifiche a script esistenti (sempre in `audit/`, mai in `SoccerMath/`): `griglia_core.py` **esteso**
(de-vig potenza/Shin e fit su linea totals qualunque, punto 4), `totals_probe.py` e
`totals_probe_analysis.py` (correzione dello stato finale dei crediti, punto 3).
Referti intermedi: `punto1_devig_produzione.md`, `punto2_calibrazione_devig.md`,
`punto3_diagnosi_sonda_totals.md`, `punto4_fit_linea_generalizzata.md`; questo file li riunisce.

---

## 0. Regole dichiarate (scritte prima dei numeri, non modificate dopo)

Le regole dei punti 1 e 4 sono scritte qui sotto **prima** di eseguire qualsiasi calcolo e non sono state
modificate dopo aver visto i numeri. Sono anche nelle docstring degli script che le applicano.

### 0.1 Regola del punto 1 — metodo di de-vig per la produzione

**Dati.** Terna 1X2. Sorgente principale: **Pinnacle di pre-chiusura** (`PSH`/`PSD`/`PSA`), perché la
produzione usa le quote del mattino. Sensibilità: **Pinnacle di chiusura** (`PSCH`/`PSCD`/`PSCA`).
L'Over/Under 2,5 Pinnacle (`P>2.5`/`P<2.5` in apertura, `PC>2.5`/`PC<2.5` in chiusura) serve solo al fit
della griglia e alla verifica di riproduzione, non alla metrica del punto 1.

**Campioni.** CSV football-data in `SoccerMath/database`, 5 leghe (Serie A, Premier League, La Liga,
Bundesliga, Ligue 1). **Campione primario: stagioni 2022/23 e 2023/24** (file `_2022`, `_2023`), mai usati
prima dal progetto. **Campione di conferma: 2024/25 e 2025/26** (file `_2024`, `_2025`). Una partita entra
se la terna 1X2 Pinnacle è completa e valida (tre quote finite > 1) e la coppia Over/Under 2,5 Pinnacle è
completa e valida.

**Metodi confrontati.** Proporzionale (quello in produzione), **potenza**, **Shin**. Il proporzionale è il
riferimento: tutte le differenze sono calcolate come metodo − proporzionale.

**Metrica.** Per partita: LogLoss e Brier dell'esito reale 1X2 sulle tre probabilità de-vigate.
ΔLogLoss = LogLoss(metodo) − LogLoss(proporzionale), ΔBrier analogo; **negativo = meglio del
proporzionale**. Le differenze sono appaiate (stessa partita).
La griglia Dixon-Coles fittata su 1X2 + Over 2,5 riproduce esattamente la terna 1X2 in ingresso
(sistema 3 incognite / 3 vincoli indipendenti): la metrica è quindi calcolata direttamente sulle
probabilità de-vigate. L'equivalenza è **verificata sui dati** (§1.2) e non assunta.

**Bootstrap.** A blocchi: **lega × stagione × data** (blocco = una giornata di una lega), 2000 repliche,
IC 95% percentile, semi dichiarati: 20261020 (ΔLogLoss/ΔBrier), 20261021 (calibrazione), 20261022
(descrittivo topmix).

**Calibrazione dell'esito più probabile.** Esito = argmax della terna de-vigata (primo massimo nell'ordine
1, X, 2). Fasce di p: **[0,55-0,65), [0,65-0,75), ≥ 0,75**. Per ogni fascia: n, p media, frequenza
osservata f, f − p con segno e IC 95% (bootstrap a blocchi, 2000 repliche).

**Regola di decisione (punto 1).**
1. Si propone il metodo **a potenza** per la produzione se, **sul campione primario e sulle quote di
   pre-chiusura**, l'IC 95% di ΔLogLoss(potenza − proporzionale) è **interamente sotto zero** *e* **sul
   campione di conferma** la stima puntuale di ΔLogLoss(potenza − proporzionale) è **≤ 0**.
2. **Shin** sostituisce la potenza **solo se** l'IC 95% di ΔLogLoss(Shin − potenza) è **interamente sotto
   zero** sul campione primario (quote di pre-chiusura).
3. In ogni altro caso: **resta il proporzionale**.
La metrica che decide è il **LogLoss**; il **Brier** è riportato come metrica secondaria e non decide.
La chiusura (`PSC`) è sensibilità e non entra nella regola.
L'esito è una **proposta**: nessuna modifica al codice di produzione in questo audit.

**Parte descrittiva (punto 1, ultimo capoverso).** Sul campione delle **3.504 partite** di PR #59
(stagioni 2024/25 e 2025/26, definite dalla copertura B365 1X2 + O/U 2,5) si contano, per ciascun metodo di
de-vig: quante scelte superano la soglia **p ≥ 0,55** del selettore `topmix_mercato_v3` (argmax della terna
de-vigata, primo massimo in ordine 1, X, 2: regola di `app.seleziona_riga_top_mix_mercato`), l'hit rate di
quelle scelte, e quante scelte cambiano esito oppure entrano/escono dalla soglia rispetto al proporzionale.
Sorgente delle quote in questa parte: **B365** (è la sorgente che definisce il campione delle 3.504 e
quella usata dal punto 5 della PR #59); la stessa tabella con **Pinnacle di pre-chiusura** sulle partite in
cui è disponibile è riportata come sensibilità. Nessuna regola di decisione: solo conteggi.

### 0.2 Regola del punto 4 — utilizzabilità del fit generalizzato

**Verifica su dati reali.** Eventi della sonda totals (`audit/data/totals_probe/`, 82 eventi) in cui
**Pinnacle ha una linea totals diversa da 2,5** e **almeno 3 ALTRI bookmaker** (Pinnacle escluso) hanno la
linea **2,5**. Per ciascuno di questi eventi si fittano due griglie con la stessa terna 1X2 e due diverse
linee totals:
* griglia **A**: 1X2 + la linea totals di Pinnacle (≠ 2,5), con il fit generalizzato;
* griglia **B**: 1X2 + la linea 2,5 degli altri libri.

Si confrontano **P(Over 2,5)**, **P(Gol)** e **P(Over 1,5)**: differenza in valore assoluto, in punti
percentuali; si riportano n, mediana e massimo.

**Fonte della terna 1X2.** La sonda totals è stata richiesta con `markets=totals` e **non contiene l'1X2**.
La terna è presa da `SoccerMath/database/live_odds.json` (h2h, libro **Pinnacle**, snapshot
2026-10-10T09:08:52Z, 8 ore prima della sonda totals): è l'unica fonte reale di 1X2 sugli stessi eventi
già presente nel repository, e nessuna nuova chiamata API è consentita. Gli eventi sono agganciati per
`id`. Il disallineamento temporale (≈ 8 ore) è un limite dichiarato, non corretto.
De-vig **proporzionale** su tutte le fonti; consenso 2,5 = **mediana** delle P(Over 2,5) de-vigate dei
libri (Pinnacle escluso) che hanno la linea 2,5.

**Regola di utilizzabilità (punto 4).**
> Il fit generalizzato è **utilizzabile** se la differenza **mediana** su P(Over 2,5) fra le due griglie è
> **≤ 1,5 punti** e la differenza **massima** è **≤ 4 punti**, con **almeno 10 eventi confrontabili**.
> Con meno di 10 eventi l'esito è **«non decidibile su questo snapshot»**.

**Conteggio finale (punto 4, ultimo capoverso).** Si riporta quanti degli 82 eventi — e quanti di quelli
con kickoff entro 7 giorni dalla chiamata — avrebbero una **linea utilizzabile** con il fit generalizzato.
Definizione dichiarata: linea utilizzabile = presenza di **almeno una linea totals** di un tipo gestito dal
fit generalizzato (mezza, intera o a quarti) offerta da almeno un bookmaker, **e** presenza della terna 1X2
Pinnacle per lo stesso evento (senza 1X2 il fit non è possibile). È un conteggio: l'ingresso di totals in
produzione si decide su una sonda nuova.

### 0.3 Regole dei punti 2 e 3 (nessuna soglia di decisione)

* **Punto 2.** Si ripete la tabella del punto 4 della PR #59 con la **variante A** (Dixon-Coles con ρ per
  partita), le **stesse fasce** ([0,55-0,65), [0,65-0,75), ≥ 0,75) e la **stessa regola di ingresso** R4
  (un mercato entra se in ogni fascia con n ≥ 100 l'IC 95% di f − p contiene lo zero **oppure**
  |f − p| ≤ 0,03; con nessuna fascia a n ≥ 100 il mercato è «non valutabile» e resta fuori). L'unica
  differenza: i tre de-vig degli input (proporzionale, potenza, Shin). Campione: le 3.504 partite B365 di
  PR #59. Nessuna nuova soglia: si riporta f − p con il segno e si dice se lo scarto **cambia** col metodo.
* **Punto 3.** Diagnosi descrittiva sui file grezzi. La classificazione dei 26 eventi che non superano la
  regola usa una **priorità dichiarata** sulle cause (prima causa che si applica, in ordine):
  (C1) Pinnacle assente sul mercato totals; (C2) Pinnacle presente con linea ≠ 2,5 (con la linea
  specificata: 1,5 / 3,5 / altra mezza / intera / a quarti); (C3) Pinnacle con la 2,5 ma meno di 3 libri
  con la 2,5; (C4) altro. Poiché la regola è un **OR** (Pinnacle 2,5 *oppure* ≥ 3 libri con la 2,5), ogni
  evento che non la supera soddisfa **anche** la condizione «meno di 3 bookmaker con la 2,5»: la
  priorità serve a non doppiare i conteggi, e il numero di libri con la 2,5 (0 / 1 / 2) è riportato a
  parte. Nessuna soglia di decisione: **la regola dell'85% resta non superata**, come nella PR #59.

<!-- SEZIONI: da qui in poi il referto e' generato da audit/referto_devig_linee.py -->

## 1. Punto 1 — metodo di de-vig per la produzione (terna 1X2 Pinnacle)

Generato da `audit/devig_produzione.py` il 2026-10-10T19:17:34Z · campione primario 3536 partite (2022/23 + 2023/24) · conferma 2625 (2024/25 + 2025/26) · nessuna modifica a `SoccerMath/`, nessun `--write`, nessuna rete, nessuna chiave.

### 1.1 Copertura per lega e stagione (prima dei risultati)

| lega | stagione | partite con risultato | 1X2 + O/U 2,5 Pinnacle pre-chiusura completi | 1X2 + O/U 2,5 Pinnacle chiusura completi | senza Pinnacle pre-chiusura | date coperte da Pinnacle pre-chiusura |
|---|---|---|---|---|---|---|
| Serie A | 2022/23 | 380 | 380 | 380 | 0 | 13/08/2022 – 04/06/2023 |
| Serie A | 2023/24 | 380 | 380 | 380 | 0 | 19/08/2023 – 02/06/2024 |
| Premier League | 2022/23 | 380 | 379 | 379 | 1 | 05/08/2022 – 28/05/2023 |
| Premier League | 2023/24 | 380 | 372 | 373 | 8 | 11/08/2023 – 19/05/2024 |
| La Liga | 2022/23 | 380 | 380 | 380 | 0 | 12/08/2022 – 04/06/2023 |
| La Liga | 2023/24 | 380 | 379 | 380 | 1 | 11/08/2023 – 26/05/2024 |
| Bundesliga | 2022/23 | 306 | 292 | 294 | 14 | 05/08/2022 – 27/05/2023 |
| Bundesliga | 2023/24 | 306 | 292 | 293 | 14 | 18/08/2023 – 18/05/2024 |
| Ligue 1 | 2022/23 | 380 | 376 | 378 | 4 | 05/08/2022 – 03/06/2023 |
| Ligue 1 | 2023/24 | 306 | 306 | 306 | 0 | 11/08/2023 – 19/05/2024 |
| Serie A | 2024/25 | 380 | 379 | 380 | 1 | 17/08/2024 – 25/05/2025 |
| Serie A | 2025/26 | 380 | 200 | 198 | 180 | 23/08/2025 – 15/01/2026 |
| Premier League | 2024/25 | 380 | 377 | 377 | 3 | 16/08/2024 – 25/05/2025 |
| Premier League | 2025/26 | 380 | 210 | 210 | 170 | 15/08/2025 – 08/01/2026 |
| La Liga | 2024/25 | 380 | 378 | 378 | 2 | 15/08/2024 – 25/05/2025 |
| La Liga | 2025/26 | 380 | 188 | 188 | 192 | 15/08/2025 – 12/01/2026 |
| Bundesliga | 2024/25 | 306 | 297 | 297 | 9 | 23/08/2024 – 17/05/2025 |
| Bundesliga | 2025/26 | 306 | 142 | 142 | 164 | 22/08/2025 – 15/01/2026 |
| Ligue 1 | 2024/25 | 306 | 304 | 304 | 2 | 16/08/2024 – 17/05/2025 |
| Ligue 1 | 2025/26 | 306 | 152 | 152 | 154 | 15/08/2025 – 04/01/2026 |

Conteggi dopo la deduplicazione su lega × data × casa × trasferta e dopo aver scartato le partite senza risultato. Le colonne Pinnacle (`PSH/PSD/PSA`, `P>2.5/P<2.5`, `PSCH/PSCD/PSCA`, `PC>2.5/PC<2.5`) sono presenti nell'intestazione di tutti i 20 CSV (2022-2025, 5 leghe): nessuna stagione e' stata esclusa per mancanza delle colonne. La copertura NON e' completa in tutte le celle: sotto il 95 % di righe compilate — Serie A 2025/26: 200/380 (52,6 %), ultima data coperta 15/01/2026; Premier League 2025/26: 210/380 (55,3 %), ultima data coperta 08/01/2026; La Liga 2025/26: 188/380 (49,5 %), ultima data coperta 12/01/2026; Bundesliga 2025/26: 142/306 (46,4 %), ultima data coperta 15/01/2026; Ligue 1 2025/26: 152/306 (49,7 %), ultima data coperta 04/01/2026. Dove Pinnacle manca la partita esce dal campione: e' una proprieta' del dato scaricato, non una scelta di questo audit.

### 1.2 Verifica: la griglia riproduce la terna de-vigata

Su 500 partite estratte a caso dal campione primario (seme 20261023) il fit Dixon-Coles su 1X2 + Over 2,5 restituisce una griglia la cui terna 1X2 differisce dalla terna de-vigata in ingresso per al piu' **5.56e-13** (residuo massimo sui 4 vincoli: 5.56e-13). Il sistema ha 3 parametri e 3 vincoli indipendenti, quindi la metrica del punto 1 puo' essere calcolata direttamente sulle probabilita' de-vigate: la griglia non aggiunge e non toglie nulla.

### 1.3 ΔLogLoss e ΔBrier appaiati rispetto al proporzionale

**campione PRIMARIO (2022/23 + 2023/24) — Pinnacle di pre-chiusura — n = 3536** (LogLoss proporzionale 0,97053, Brier proporzionale 0,57748)

| confronto (metodo − proporzionale) | metrica | media per partita | IC 95% a blocchi | lettura |
|---|---|---|---|---|
| potenza | ΔLogLoss | -0,000517 | [-0,001106; 0,000091] | IC contiene 0 |
| potenza (ΔBrier) | ΔBrier | -0,000252 | [-0,000619; 0,000114] | IC contiene 0 |
| Shin | ΔLogLoss | -0,000498 | [-0,000920; -0,000084] | IC tutta < 0 |
| Shin (ΔBrier) | ΔBrier | -0,000224 | [-0,000470; 0,000025] | IC contiene 0 |
| Shin-potenza | ΔLogLoss | 0,000019 | [-0,000204; 0,000221] | IC contiene 0 |

**campione di CONFERMA (2024/25 + 2025/26) — Pinnacle di pre-chiusura — n = 2625** (LogLoss proporzionale 0,96837, Brier proporzionale 0,57616)

| confronto (metodo − proporzionale) | metrica | media per partita | IC 95% a blocchi | lettura |
|---|---|---|---|---|
| potenza | ΔLogLoss | -0,000794 | [-0,001596; 0,000021] | IC contiene 0 |
| potenza (ΔBrier) | ΔBrier | -0,000345 | [-0,000831; 0,000128] | IC contiene 0 |
| Shin | ΔLogLoss | -0,000652 | [-0,001216; -0,000084] | IC tutta < 0 |
| Shin (ΔBrier) | ΔBrier | -0,000281 | [-0,000608; 0,000032] | IC contiene 0 |
| Shin-potenza | ΔLogLoss | 0,000142 | [-0,000134; 0,000408] | IC contiene 0 |

Negativo = meglio del proporzionale. Blocchi = lega × stagione × data; 2000 repliche; seme 20261020.

### 1.4 Sensibilità: Pinnacle di chiusura

| campione (chiusura) | metodo | n | ΔLogLoss medio | IC 95% | lettura |
|---|---|---|---|---|---|
| primario (2022/23 + 2023/24) | potenza | 3543 | -0,000512 | [-0,001061; 0,000050] | IC contiene 0 |
| primario (2022/23 + 2023/24) | Shin | 3543 | -0,000485 | [-0,000860; -0,000110] | IC tutta < 0 |
| conferma (2024/25 + 2025/26) | potenza | 2623 | -0,000721 | [-0,001402; -0,000006] | IC tutta < 0 |
| conferma (2024/25 + 2025/26) | Shin | 2623 | -0,000558 | [-0,001043; -0,000052] | IC tutta < 0 |

### 1.5 Calibrazione dell'esito più probabile (argmax)

**PRIMARIO (2022/23 + 2023/24) — n = 3536**

| de-vig | fascia di p | n | p media | frequenza f | f − p [IC 95%] |
|---|---|---|---|---|---|
| proporzionale | 0,55-0,65 | 693 | 59,46 % | 60,89 % | 1,44 pt [-2,46 pt; 5,15 pt] |
| proporzionale | 0,65-0,75 | 443 | 69,56 % | 73,81 % | 4,26 pt [0,23 pt; 8,40 pt] |
| proporzionale | ≥0,75 | 178 | 79,95 % | 79,78 % | -0,17 pt [-5,80 pt; 5,47 pt] |
| potenza | 0,55-0,65 | 708 | 59,42 % | 60,45 % | 1,03 pt [-2,66 pt; 4,65 pt] |
| potenza | 0,65-0,75 | 446 | 69,61 % | 71,08 % | 1,47 pt [-2,69 pt; 5,63 pt] |
| potenza | ≥0,75 | 231 | 80,52 % | 80,52 % | 0,00 pt [-5,16 pt; 5,17 pt] |
| Shin | 0,55-0,65 | 709 | 59,48 % | 60,51 % | 1,03 pt [-2,64 pt; 4,67 pt] |
| Shin | 0,65-0,75 | 443 | 69,66 % | 72,23 % | 2,57 pt [-1,65 pt; 6,71 pt] |
| Shin | ≥0,75 | 212 | 80,32 % | 80,19 % | -0,13 pt [-5,46 pt; 5,11 pt] |

**CONFERMA (2024/25 + 2025/26) — n = 2625**

| de-vig | fascia di p | n | p media | frequenza f | f − p [IC 95%] |
|---|---|---|---|---|---|
| proporzionale | 0,55-0,65 | 516 | 59,40 % | 59,30 % | -0,10 pt [-4,41 pt; 4,06 pt] |
| proporzionale | 0,65-0,75 | 334 | 69,63 % | 74,85 % | 5,22 pt [0,46 pt; 9,77 pt] |
| proporzionale | ≥0,75 | 141 | 79,22 % | 83,69 % | 4,47 pt [-2,43 pt; 10,66 pt] |
| potenza | 0,55-0,65 | 519 | 59,36 % | 58,96 % | -0,40 pt [-4,83 pt; 3,80 pt] |
| potenza | 0,65-0,75 | 349 | 69,79 % | 70,77 % | 0,98 pt [-3,74 pt; 5,64 pt] |
| potenza | ≥0,75 | 179 | 80,31 % | 82,68 % | 2,37 pt [-3,59 pt; 7,94 pt] |
| Shin | 0,55-0,65 | 513 | 59,39 % | 59,26 % | -0,13 pt [-4,49 pt; 4,01 pt] |
| Shin | 0,65-0,75 | 346 | 69,68 % | 71,68 % | 1,99 pt [-2,60 pt; 6,45 pt] |
| Shin | ≥0,75 | 168 | 79,86 % | 83,33 % | 3,47 pt [-2,73 pt; 9,33 pt] |

### 1.6 Esito della regola dichiarata (R1.7)

| condizione | esito |
|---|---|
| (a1) IC 95% di ΔLogLoss(potenza − proporzionale) tutta < 0 sul primario | NO (IC [-0,001106; 0,000091]) |
| (a2) stima puntuale di ΔLogLoss(potenza − proporzionale) ≤ 0 sulla conferma | SÌ (puntuale -0,000794) |
| (b) IC 95% di ΔLogLoss(Shin − potenza) tutta < 0 sul primario | NO (IC [-0,000204; 0,000221]) |

**Proposta: proporzionale.** (Solo proposta: nessuna modifica al codice di produzione in questo audit.)

### 1.7 Descrittivo: soglia p ≥ 0,55 di topmix_mercato_v3 sulle 3.504 partite

Campione delle 3.504 partite di PR #59 (B365, 2024/25 + 2025/26). Scelta = argmax della terna de-vigata (primo massimo in ordine 1, X, 2) con p ≥ 0,55, come in `app.seleziona_riga_top_mix_mercato`. Nessuna regola di decisione.

#### 1.7.1 Sorgente B365 (definisce il campione)

| de-vig | scelte (p ≥ 0,55) | hit rate | cambia esito (su 3504) | cambia esito restando sopra soglia | entra | esce |
|---|---|---|---|---|---|---|
| proporzionale | 1302 | 67,51 % | — | — | — | — |
| potenza | 1465 | 66,28 % | 0 / 3504 | 0 | 163 (hit 56,44 %) | 0 (hit n/d) |
| Shin | 1407 | 66,45 % | 0 / 3504 | 0 | 105 (hit 53,33 %) | 0 (hit n/d) |

Su 3504 partite (attese 3.504 di PR #59). «Cambia esito» e' contato su tutte le partite del campione; «cambia esito restando sopra soglia» solo fra le scelte ammesse da entrambi i metodi. Tra parentesi l'hit rate delle scelte che entrano/escono.

**Perche' «cambia esito» e' 0 con ogni metodo:** proporzionale, potenza e Shin sono trasformazioni *monotone crescenti* di π_i = 1/q_i (la potenza con esponente k ≥ 1, Shin con z < 1), quindi l'argmax della terna e' lo stesso per costruzione: nessuna scelta puo' cambiare esito. Puo' cambiare solo il livello di p, e qui il livello sale (potenza e Shin tolgono meno al favorito del proporzionale): entrano solo nuove scelte, nessuna esce.

**Controllo di parita' con PR #49/PR #59:** con il de-vig proporzionale le scelte di mercato sono 1302 con hit rate 67,51 %: coincidono con i 1302 / 67,5 % del replay `topmix_mercato_v3`.

#### 1.7.2 Sensibilità: Pinnacle di pre-chiusura (stesse partite, dove disponibile)

| de-vig | scelte (p ≥ 0,55) | hit rate | cambia esito | cambia esito restando sopra soglia | entra | esce |
|---|---|---|---|---|---|---|
| proporzionale | 991 | 68,01 % | — | — | — | — |
| potenza | 1047 | 66,95 % | 0 / 2625 | 0 | 56 (hit 48,21 %) | 0 (hit n/d) |
| Shin | 1027 | 67,38 % | 0 / 2625 | 0 | 36 (hit 50,00 %) | 0 (hit n/d) |

Stesse partite, filtrate su quelle con terna Pinnacle di pre-chiusura e O/U 2,5 Pinnacle completi: 2625 su 3504. La colonna «cambia esito» e' calcolata su questo sottoinsieme.

## 2. Punto 2 — calibrazione dei derivati rifatta con tre de-vig degli input

Generato da `audit/griglia_devig.py` il 2026-10-10T19:35:14Z · campione 3504 partite (B365, 2024/25 + 2025/26) · variante **A** (Dixon-Coles con ρ per partita) · stesse fasce e stessa regola di ingresso R4 di PR #59 · nessuna modifica a `SoccerMath/`, nessun `--write`, nessuna rete, nessuna chiave.

### 2.1 Campione e riproduzione del fit

| metodo di de-vig | partite | residuo massimo sui 4 vincoli | ρ mediano | λ mediano | μ mediano |
|---|---|---|---|---|---|
| proporzionale | 3504 | 1.5e-12 | -0,0781 | 1,478 | 1,168 |
| Shin | 3504 | 1.2e-12 | -0,0723 | 1,484 | 1,160 |
| potenza | 3504 | 2.0e-12 | -0,0663 | 1,485 | 1,158 |

**Controllo di parità con PR #59 (de-vig proporzionale).** Confrontate 14 celle (mercato, fascia) con la tabella del punto 4 di `audit/results/griglia_varianti.md`: tutti i conteggi n coincidono esattamente e il massimo scarto su f − p è **0.04 punti** (dovuto all'arrotondamento a un decimale del referto PR #59). Le colonne potenza e Shin sono calcolate con lo stesso codice e gli stessi semi: l'unica differenza è il de-vig degli input.

### 2.2 f − p con segno, per mercato, fascia e metodo

Esito valutato: quello con p più alta nella coppia evento/complemento (p ≥ 0,5). f − p in punti percentuali con IC 95% a blocchi (lega × stagione × data, 2000 repliche, seme 20261011).

#### Gol — esiti: No Gol / Gol

| de-vig | fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|---|
| proporzionale | 0,55-0,65 | 1661 | 58,68 % | 58,64 % | -0,0 pt [-2,5 pt; 2,3 pt] | sì |
| proporzionale | 0,65-0,75 | 126 | 67,37 % | 63,49 % | -3,9 pt [-12,6 pt; 5,1 pt] | sì |
| proporzionale | ≥0,75 | 0 | n/d | n/d | n/d | no |
| potenza | 0,55-0,65 | 1695 | 58,79 % | 58,58 % | -0,2 pt [-2,6 pt; 2,1 pt] | sì |
| potenza | 0,65-0,75 | 181 | 67,44 % | 60,22 % | -7,2 pt [-14,4 pt; 0,3 pt] | sì |
| potenza | ≥0,75 | 0 | n/d | n/d | n/d | no |
| Shin | 0,55-0,65 | 1684 | 58,76 % | 59,14 % | 0,4 pt [-1,9 pt; 2,7 pt] | sì |
| Shin | 0,65-0,75 | 155 | 67,45 % | 59,35 % | -8,1 pt [-15,5 pt; -0,0 pt] | sì |
| Shin | ≥0,75 | 0 | n/d | n/d | n/d | no |

| de-vig | esito R4 |
|---|---|
| proporzionale | CALIBRATO: entra nella lista |
| potenza | CALIBRATO: entra nella lista |
| Shin | non calibrato: resta fuori |

#### Over 1.5 — esiti: Under 1.5 / Over 1.5

| de-vig | fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|---|
| proporzionale | 0,55-0,65 | 146 | 62,17 % | 60,96 % | -1,2 pt [-9,7 pt; 6,7 pt] | sì |
| proporzionale | 0,65-0,75 | 1134 | 71,26 % | 71,25 % | -0,0 pt [-2,6 pt; 2,6 pt] | sì |
| proporzionale | ≥0,75 | 2222 | 81,16 % | 81,32 % | 0,2 pt [-1,5 pt; 1,7 pt] | sì |
| potenza | 0,55-0,65 | 180 | 61,92 % | 63,89 % | 2,0 pt [-5,5 pt; 8,8 pt] | sì |
| potenza | 0,65-0,75 | 1119 | 71,05 % | 71,22 % | 0,2 pt [-2,5 pt; 2,9 pt] | sì |
| potenza | ≥0,75 | 2195 | 81,54 % | 81,37 % | -0,2 pt [-1,9 pt; 1,4 pt] | sì |
| Shin | 0,55-0,65 | 163 | 61,93 % | 63,80 % | 1,9 pt [-5,8 pt; 9,3 pt] | sì |
| Shin | 0,65-0,75 | 1124 | 71,08 % | 71,17 % | 0,1 pt [-2,5 pt; 2,8 pt] | sì |
| Shin | ≥0,75 | 2210 | 81,41 % | 81,31 % | -0,1 pt [-1,7 pt; 1,5 pt] | sì |

| de-vig | esito R4 |
|---|---|
| proporzionale | CALIBRATO: entra nella lista |
| potenza | CALIBRATO: entra nella lista |
| Shin | CALIBRATO: entra nella lista |

#### Over 3.5 — esiti: Under 3.5 / Over 3.5

| de-vig | fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|---|
| proporzionale | 0,55-0,65 | 802 | 60,16 % | 60,22 % | 0,1 pt [-3,6 pt; 3,5 pt] | sì |
| proporzionale | 0,65-0,75 | 1593 | 69,97 % | 69,93 % | -0,0 pt [-2,3 pt; 2,1 pt] | sì |
| proporzionale | ≥0,75 | 894 | 79,18 % | 81,10 % | 1,9 pt [-0,8 pt; 4,5 pt] | sì |
| potenza | 0,55-0,65 | 674 | 60,25 % | 61,72 % | 1,5 pt [-2,6 pt; 5,1 pt] | sì |
| potenza | 0,65-0,75 | 1581 | 69,78 % | 69,89 % | 0,1 pt [-2,1 pt; 2,2 pt] | sì |
| potenza | ≥0,75 | 903 | 79,67 % | 80,95 % | 1,3 pt [-1,4 pt; 3,9 pt] | sì |
| Shin | 0,55-0,65 | 821 | 59,53 % | 60,41 % | 0,9 pt [-2,7 pt; 4,3 pt] | sì |
| Shin | 0,65-0,75 | 1589 | 69,87 % | 69,86 % | -0,0 pt [-2,2 pt; 2,1 pt] | sì |
| Shin | ≥0,75 | 895 | 79,53 % | 81,12 % | 1,6 pt [-1,1 pt; 4,2 pt] | sì |

| de-vig | esito R4 |
|---|---|
| proporzionale | CALIBRATO: entra nella lista |
| potenza | CALIBRATO: entra nella lista |
| Shin | CALIBRATO: entra nella lista |

#### 1X — esiti: 2 / 1X

| de-vig | fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|---|
| proporzionale | 0,55-0,65 | 775 | 60,08 % | 58,58 % | -1,5 pt [-4,9 pt; 1,9 pt] | sì |
| proporzionale | 0,65-0,75 | 938 | 70,07 % | 70,79 % | 0,7 pt [-2,3 pt; 3,6 pt] | sì |
| proporzionale | ≥0,75 | 1443 | 83,45 % | 84,55 % | 1,1 pt [-0,8 pt; 3,0 pt] | sì |
| potenza | 0,55-0,65 | 818 | 59,92 % | 58,92 % | -1,0 pt [-4,4 pt; 2,3 pt] | sì |
| potenza | 0,65-0,75 | 881 | 70,04 % | 70,37 % | 0,3 pt [-2,8 pt; 3,4 pt] | sì |
| potenza | ≥0,75 | 1511 | 83,96 % | 84,32 % | 0,4 pt [-1,5 pt; 2,3 pt] | sì |
| Shin | 0,55-0,65 | 804 | 59,98 % | 58,96 % | -1,0 pt [-4,4 pt; 2,3 pt] | sì |
| Shin | 0,65-0,75 | 896 | 70,07 % | 70,42 % | 0,4 pt [-2,7 pt; 3,3 pt] | sì |
| Shin | ≥0,75 | 1490 | 83,89 % | 84,36 % | 0,5 pt [-1,4 pt; 2,4 pt] | sì |

| de-vig | esito R4 |
|---|---|
| proporzionale | CALIBRATO: entra nella lista |
| potenza | CALIBRATO: entra nella lista |
| Shin | CALIBRATO: entra nella lista |

#### X2 — esiti: 1 / X2

| de-vig | fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|---|
| proporzionale | 0,55-0,65 | 1222 | 59,87 % | 59,74 % | -0,1 pt [-2,8 pt; 2,6 pt] | sì |
| proporzionale | 0,65-0,75 | 916 | 69,64 % | 72,82 % | 3,2 pt [0,2 pt; 5,9 pt] | sì |
| proporzionale | ≥0,75 | 727 | 81,31 % | 85,28 % | 4,0 pt [1,5 pt; 6,5 pt] | sì |
| potenza | 0,55-0,65 | 1234 | 59,63 % | 59,00 % | -0,6 pt [-3,3 pt; 2,2 pt] | sì |
| potenza | 0,65-0,75 | 887 | 69,68 % | 71,59 % | 1,9 pt [-1,0 pt; 4,8 pt] | sì |
| potenza | ≥0,75 | 823 | 81,83 % | 83,84 % | 2,0 pt [-0,4 pt; 4,3 pt] | sì |
| Shin | 0,55-0,65 | 1225 | 59,71 % | 59,10 % | -0,6 pt [-3,3 pt; 2,2 pt] | sì |
| Shin | 0,65-0,75 | 914 | 69,76 % | 71,55 % | 1,8 pt [-1,1 pt; 4,7 pt] | sì |
| Shin | ≥0,75 | 775 | 81,83 % | 84,77 % | 2,9 pt [0,5 pt; 5,4 pt] | sì |

| de-vig | esito R4 |
|---|---|
| proporzionale | non calibrato: resta fuori |
| potenza | CALIBRATO: entra nella lista |
| Shin | CALIBRATO: entra nella lista |

#### 12 — esiti: X / 12

| de-vig | fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|---|
| proporzionale | 0,55-0,65 | 2 | 63,76 % | 50,00 % | -13,8 pt [-63,4 pt; 35,8 pt] | no |
| proporzionale | 0,65-0,75 | 2039 | 71,97 % | 71,11 % | -0,9 pt [-2,8 pt; 1,1 pt] | sì |
| proporzionale | ≥0,75 | 1463 | 79,59 % | 79,97 % | 0,4 pt [-1,6 pt; 2,4 pt] | sì |
| potenza | 0,55-0,65 | 2 | 63,57 % | 50,00 % | -13,6 pt [-63,1 pt; 36,0 pt] | no |
| potenza | 0,65-0,75 | 1825 | 71,93 % | 70,79 % | -1,1 pt [-3,1 pt; 0,9 pt] | sì |
| potenza | ≥0,75 | 1677 | 79,88 % | 79,19 % | -0,7 pt [-2,6 pt; 1,2 pt] | sì |
| Shin | 0,55-0,65 | 2 | 63,62 % | 50,00 % | -13,6 pt [-63,2 pt; 36,0 pt] | no |
| Shin | 0,65-0,75 | 1877 | 71,93 % | 70,70 % | -1,2 pt [-3,2 pt; 0,8 pt] | sì |
| Shin | ≥0,75 | 1625 | 79,64 % | 79,57 % | -0,1 pt [-2,1 pt; 1,9 pt] | sì |

| de-vig | esito R4 |
|---|---|
| proporzionale | CALIBRATO: entra nella lista |
| potenza | CALIBRATO: entra nella lista |
| Shin | CALIBRATO: entra nella lista |

#### 1+Over 1.5 — esiti: non (1 + Over 1,5) / 1+Over 1.5

| de-vig | fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|---|
| proporzionale | 0,55-0,65 | 959 | 59,83 % | 61,84 % | 2,0 pt [-1,1 pt; 4,9 pt] | sì |
| proporzionale | 0,65-0,75 | 1027 | 69,90 % | 72,93 % | 3,0 pt [0,4 pt; 5,9 pt] | sì |
| proporzionale | ≥0,75 | 1068 | 82,61 % | 85,30 % | 2,7 pt [0,5 pt; 4,7 pt] | sì |
| potenza | 0,55-0,65 | 926 | 60,00 % | 61,77 % | 1,8 pt [-1,3 pt; 4,9 pt] | sì |
| potenza | 0,65-0,75 | 1004 | 69,98 % | 72,21 % | 2,2 pt [-0,4 pt; 5,1 pt] | sì |
| potenza | ≥0,75 | 1110 | 83,02 % | 85,14 % | 2,1 pt [-0,0 pt; 4,2 pt] | sì |
| Shin | 0,55-0,65 | 927 | 59,90 % | 61,70 % | 1,8 pt [-1,3 pt; 4,9 pt] | sì |
| Shin | 0,65-0,75 | 1018 | 69,89 % | 72,50 % | 2,6 pt [-0,1 pt; 5,3 pt] | sì |
| Shin | ≥0,75 | 1098 | 82,89 % | 85,15 % | 2,3 pt [0,1 pt; 4,3 pt] | sì |

| de-vig | esito R4 |
|---|---|
| proporzionale | non calibrato: resta fuori |
| potenza | CALIBRATO: entra nella lista |
| Shin | CALIBRATO: entra nella lista |

#### 2+Over 1.5 — esiti: non (2 + Over 1,5) / 2+Over 1.5

| de-vig | fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|---|
| proporzionale | 0,55-0,65 | 482 | 60,23 % | 60,58 % | 0,3 pt [-4,1 pt; 4,8 pt] | sì |
| proporzionale | 0,65-0,75 | 669 | 70,50 % | 69,36 % | -1,1 pt [-4,7 pt; 2,4 pt] | sì |
| proporzionale | ≥0,75 | 2116 | 85,10 % | 85,07 % | -0,0 pt [-1,5 pt; 1,4 pt] | sì |
| potenza | 0,55-0,65 | 470 | 60,13 % | 60,00 % | -0,1 pt [-4,7 pt; 4,2 pt] | sì |
| potenza | 0,65-0,75 | 659 | 70,43 % | 69,80 % | -0,6 pt [-4,2 pt; 2,9 pt] | sì |
| potenza | ≥0,75 | 2131 | 85,69 % | 84,89 % | -0,8 pt [-2,3 pt; 0,6 pt] | sì |
| Shin | 0,55-0,65 | 473 | 60,11 % | 60,47 % | 0,4 pt [-4,2 pt; 4,8 pt] | sì |
| Shin | 0,65-0,75 | 665 | 70,43 % | 69,62 % | -0,8 pt [-4,3 pt; 2,7 pt] | sì |
| Shin | ≥0,75 | 2125 | 85,54 % | 84,89 % | -0,6 pt [-2,1 pt; 0,8 pt] | sì |

| de-vig | esito R4 |
|---|---|
| proporzionale | CALIBRATO: entra nella lista |
| potenza | CALIBRATO: entra nella lista |
| Shin | CALIBRATO: entra nella lista |

#### 1X+Over 1.5 — esiti: non (1X + Over 1,5) / 1X+Over 1.5

| de-vig | fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|---|
| proporzionale | 0,55-0,65 | 1389 | 59,70 % | 59,97 % | 0,3 pt [-2,3 pt; 3,0 pt] | sì |
| proporzionale | 0,65-0,75 | 846 | 69,50 % | 70,21 % | 0,7 pt [-2,6 pt; 3,9 pt] | sì |
| proporzionale | ≥0,75 | 368 | 79,70 % | 84,24 % | 4,5 pt [0,8 pt; 8,2 pt] | sì |
| potenza | 0,55-0,65 | 1341 | 59,69 % | 58,99 % | -0,7 pt [-3,3 pt; 2,0 pt] | sì |
| potenza | 0,65-0,75 | 844 | 69,45 % | 70,50 % | 1,0 pt [-2,2 pt; 4,2 pt] | sì |
| potenza | ≥0,75 | 467 | 80,28 % | 80,73 % | 0,4 pt [-3,2 pt; 4,1 pt] | sì |
| Shin | 0,55-0,65 | 1354 | 59,69 % | 59,23 % | -0,5 pt [-3,1 pt; 2,2 pt] | sì |
| Shin | 0,65-0,75 | 846 | 69,46 % | 70,33 % | 0,9 pt [-2,5 pt; 4,0 pt] | sì |
| Shin | ≥0,75 | 441 | 80,08 % | 81,63 % | 1,6 pt [-2,2 pt; 5,2 pt] | sì |

| de-vig | esito R4 |
|---|---|
| proporzionale | non calibrato: resta fuori |
| potenza | CALIBRATO: entra nella lista |
| Shin | CALIBRATO: entra nella lista |

#### 1X+Under 3.5 — esiti: non (1X + Under 3,5) / 1X+Under 3.5

| de-vig | fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|---|
| proporzionale | 0,55-0,65 | 1633 | 59,21 % | 61,05 % | 1,8 pt [-0,5 pt; 4,2 pt] | sì |
| proporzionale | 0,65-0,75 | 430 | 68,80 % | 71,86 % | 3,1 pt [-1,1 pt; 7,3 pt] | sì |
| proporzionale | ≥0,75 | 122 | 79,81 % | 83,61 % | 3,8 pt [-3,3 pt; 10,2 pt] | sì |
| potenza | 0,55-0,65 | 1619 | 59,32 % | 59,98 % | 0,7 pt [-1,7 pt; 3,0 pt] | sì |
| potenza | 0,65-0,75 | 489 | 68,75 % | 69,33 % | 0,6 pt [-3,4 pt; 4,7 pt] | sì |
| potenza | ≥0,75 | 154 | 80,28 % | 83,77 % | 3,5 pt [-2,8 pt; 9,2 pt] | sì |
| Shin | 0,55-0,65 | 1623 | 59,31 % | 60,38 % | 1,1 pt [-1,2 pt; 3,5 pt] | sì |
| Shin | 0,65-0,75 | 476 | 68,80 % | 70,38 % | 1,6 pt [-2,4 pt; 5,7 pt] | sì |
| Shin | ≥0,75 | 140 | 80,19 % | 83,57 % | 3,4 pt [-3,4 pt; 9,3 pt] | sì |

| de-vig | esito R4 |
|---|---|
| proporzionale | CALIBRATO: entra nella lista |
| potenza | CALIBRATO: entra nella lista |
| Shin | CALIBRATO: entra nella lista |

#### X2+Under 3.5 (extra) — esiti: non (X2 + Under 3,5) / X2+Under 3.5

| de-vig | fascia di p | n | p media | frequenza f | f − p [IC 95%] | conta (n ≥ 100) |
|---|---|---|---|---|---|---|
| proporzionale | 0,55-0,65 | 1355 | 59,39 % | 58,82 % | -0,6 pt [-3,2 pt; 1,9 pt] | sì |
| proporzionale | 0,65-0,75 | 666 | 69,58 % | 72,67 % | 3,1 pt [-0,3 pt; 6,4 pt] | sì |
| proporzionale | ≥0,75 | 451 | 81,15 % | 82,93 % | 1,8 pt [-1,6 pt; 5,4 pt] | sì |
| potenza | 0,55-0,65 | 1321 | 59,40 % | 58,59 % | -0,8 pt [-3,5 pt; 1,8 pt] | sì |
| potenza | 0,65-0,75 | 672 | 69,37 % | 70,98 % | 1,6 pt [-1,8 pt; 5,0 pt] | sì |
| potenza | ≥0,75 | 536 | 81,80 % | 82,09 % | 0,3 pt [-2,9 pt; 3,7 pt] | sì |
| Shin | 0,55-0,65 | 1330 | 59,38 % | 58,72 % | -0,7 pt [-3,4 pt; 1,9 pt] | sì |
| Shin | 0,65-0,75 | 676 | 69,39 % | 71,60 % | 2,2 pt [-1,1 pt; 5,6 pt] | sì |
| Shin | ≥0,75 | 510 | 81,48 % | 82,55 % | 1,1 pt [-2,2 pt; 4,6 pt] | sì |

| de-vig | esito R4 |
|---|---|
| proporzionale | CALIBRATO: entra nella lista |
| potenza | CALIBRATO: entra nella lista |
| Shin | CALIBRATO: entra nella lista |

### 2.3 Sintesi: lo scarto cambia col metodo di de-vig?

| mercato | f − p proporzionale (fasce con n ≥ 100) | f − p potenza | f − p Shin | l'esito R4 cambia col metodo |
|---|---|---|---|---|
| Gol | 0,55-0,65: -0,0 pt; 0,65-0,75: -3,9 pt | 0,55-0,65: -0,2 pt; 0,65-0,75: -7,2 pt | 0,55-0,65: 0,4 pt; 0,65-0,75: -8,1 pt | sì |
| Over 1.5 | 0,55-0,65: -1,2 pt; 0,65-0,75: -0,0 pt; ≥0,75: 0,2 pt | 0,55-0,65: 2,0 pt; 0,65-0,75: 0,2 pt; ≥0,75: -0,2 pt | 0,55-0,65: 1,9 pt; 0,65-0,75: 0,1 pt; ≥0,75: -0,1 pt | no |
| Over 3.5 | 0,55-0,65: 0,1 pt; 0,65-0,75: -0,0 pt; ≥0,75: 1,9 pt | 0,55-0,65: 1,5 pt; 0,65-0,75: 0,1 pt; ≥0,75: 1,3 pt | 0,55-0,65: 0,9 pt; 0,65-0,75: -0,0 pt; ≥0,75: 1,6 pt | no |
| 1X | 0,55-0,65: -1,5 pt; 0,65-0,75: 0,7 pt; ≥0,75: 1,1 pt | 0,55-0,65: -1,0 pt; 0,65-0,75: 0,3 pt; ≥0,75: 0,4 pt | 0,55-0,65: -1,0 pt; 0,65-0,75: 0,4 pt; ≥0,75: 0,5 pt | no |
| X2 | 0,55-0,65: -0,1 pt; 0,65-0,75: 3,2 pt; ≥0,75: 4,0 pt | 0,55-0,65: -0,6 pt; 0,65-0,75: 1,9 pt; ≥0,75: 2,0 pt | 0,55-0,65: -0,6 pt; 0,65-0,75: 1,8 pt; ≥0,75: 2,9 pt | sì |
| 12 | 0,65-0,75: -0,9 pt; ≥0,75: 0,4 pt | 0,65-0,75: -1,1 pt; ≥0,75: -0,7 pt | 0,65-0,75: -1,2 pt; ≥0,75: -0,1 pt | no |
| 1+Over 1.5 | 0,55-0,65: 2,0 pt; 0,65-0,75: 3,0 pt; ≥0,75: 2,7 pt | 0,55-0,65: 1,8 pt; 0,65-0,75: 2,2 pt; ≥0,75: 2,1 pt | 0,55-0,65: 1,8 pt; 0,65-0,75: 2,6 pt; ≥0,75: 2,3 pt | sì |
| 2+Over 1.5 | 0,55-0,65: 0,3 pt; 0,65-0,75: -1,1 pt; ≥0,75: -0,0 pt | 0,55-0,65: -0,1 pt; 0,65-0,75: -0,6 pt; ≥0,75: -0,8 pt | 0,55-0,65: 0,4 pt; 0,65-0,75: -0,8 pt; ≥0,75: -0,6 pt | no |
| 1X+Over 1.5 | 0,55-0,65: 0,3 pt; 0,65-0,75: 0,7 pt; ≥0,75: 4,5 pt | 0,55-0,65: -0,7 pt; 0,65-0,75: 1,0 pt; ≥0,75: 0,4 pt | 0,55-0,65: -0,5 pt; 0,65-0,75: 0,9 pt; ≥0,75: 1,6 pt | sì |
| 1X+Under 3.5 | 0,55-0,65: 1,8 pt; 0,65-0,75: 3,1 pt; ≥0,75: 3,8 pt | 0,55-0,65: 0,7 pt; 0,65-0,75: 0,6 pt; ≥0,75: 3,5 pt | 0,55-0,65: 1,1 pt; 0,65-0,75: 1,6 pt; ≥0,75: 3,4 pt | no |
| X2+Under 3.5 (extra) | 0,55-0,65: -0,6 pt; 0,65-0,75: 3,1 pt; ≥0,75: 1,8 pt | 0,55-0,65: -0,8 pt; 0,65-0,75: 1,6 pt; ≥0,75: 0,3 pt | 0,55-0,65: -0,7 pt; 0,65-0,75: 2,2 pt; ≥0,75: 1,1 pt | no |

#### 2.3.1 I tre mercati fuori lista: lo scarto cambia col metodo?

**X2.**
 proporzionale: 0,55-0,65: -0,1 pt [-2,8 pt; 2,6 pt], 0,65-0,75: 3,2 pt [0,2 pt; 5,9 pt], ≥0,75: 4,0 pt [1,5 pt; 6,5 pt]. Esito R4: non calibrato: resta fuori.
 potenza: 0,55-0,65: -0,6 pt [-3,3 pt; 2,2 pt], 0,65-0,75: 1,9 pt [-1,0 pt; 4,8 pt], ≥0,75: 2,0 pt [-0,4 pt; 4,3 pt]. Esito R4: CALIBRATO: entra nella lista.
 Shin: 0,55-0,65: -0,6 pt [-3,3 pt; 2,2 pt], 0,65-0,75: 1,8 pt [-1,1 pt; 4,7 pt], ≥0,75: 2,9 pt [0,5 pt; 5,4 pt]. Esito R4: CALIBRATO: entra nella lista.
  - fascia 0,55-0,65: lo scarto passa da -0,1 pt (proporzionale) a -0,6 pt (potenza) e -0,6 pt (Shin): resta dello stesso segno, ampiezza massima 0,5 pt.
  - fascia 0,65-0,75: lo scarto passa da 3,2 pt (proporzionale) a 1,9 pt (potenza) e 1,8 pt (Shin): resta dello stesso segno, ampiezza massima 1,4 pt.
  - fascia ≥0,75: lo scarto passa da 4,0 pt (proporzionale) a 2,0 pt (potenza) e 2,9 pt (Shin): resta dello stesso segno, ampiezza massima 2,0 pt.

**1+Over 1.5.**
 proporzionale: 0,55-0,65: 2,0 pt [-1,1 pt; 4,9 pt], 0,65-0,75: 3,0 pt [0,4 pt; 5,9 pt], ≥0,75: 2,7 pt [0,5 pt; 4,7 pt]. Esito R4: non calibrato: resta fuori.
 potenza: 0,55-0,65: 1,8 pt [-1,3 pt; 4,9 pt], 0,65-0,75: 2,2 pt [-0,4 pt; 5,1 pt], ≥0,75: 2,1 pt [-0,0 pt; 4,2 pt]. Esito R4: CALIBRATO: entra nella lista.
 Shin: 0,55-0,65: 1,8 pt [-1,3 pt; 4,9 pt], 0,65-0,75: 2,6 pt [-0,1 pt; 5,3 pt], ≥0,75: 2,3 pt [0,1 pt; 4,3 pt]. Esito R4: CALIBRATO: entra nella lista.
  - fascia 0,55-0,65: lo scarto passa da 2,0 pt (proporzionale) a 1,8 pt (potenza) e 1,8 pt (Shin): resta dello stesso segno, ampiezza massima 0,2 pt.
  - fascia 0,65-0,75: lo scarto passa da 3,0 pt (proporzionale) a 2,2 pt (potenza) e 2,6 pt (Shin): resta dello stesso segno, ampiezza massima 0,8 pt.
  - fascia ≥0,75: lo scarto passa da 2,7 pt (proporzionale) a 2,1 pt (potenza) e 2,3 pt (Shin): resta dello stesso segno, ampiezza massima 0,6 pt.

**1X+Over 1.5.**
 proporzionale: 0,55-0,65: 0,3 pt [-2,3 pt; 3,0 pt], 0,65-0,75: 0,7 pt [-2,6 pt; 3,9 pt], ≥0,75: 4,5 pt [0,8 pt; 8,2 pt]. Esito R4: non calibrato: resta fuori.
 potenza: 0,55-0,65: -0,7 pt [-3,3 pt; 2,0 pt], 0,65-0,75: 1,0 pt [-2,2 pt; 4,2 pt], ≥0,75: 0,4 pt [-3,2 pt; 4,1 pt]. Esito R4: CALIBRATO: entra nella lista.
 Shin: 0,55-0,65: -0,5 pt [-3,1 pt; 2,2 pt], 0,65-0,75: 0,9 pt [-2,5 pt; 4,0 pt], ≥0,75: 1,6 pt [-2,2 pt; 5,2 pt]. Esito R4: CALIBRATO: entra nella lista.
  - fascia 0,55-0,65: lo scarto passa da 0,3 pt (proporzionale) a -0,7 pt (potenza) e -0,5 pt (Shin): **cambia segno**.
  - fascia 0,65-0,75: lo scarto passa da 0,7 pt (proporzionale) a 1,0 pt (potenza) e 0,9 pt (Shin): resta dello stesso segno, ampiezza massima 0,3 pt.
  - fascia ≥0,75: lo scarto passa da 4,5 pt (proporzionale) a 0,4 pt (potenza) e 1,6 pt (Shin): resta dello stesso segno, ampiezza massima 4,1 pt.

### 2.4 Doppia chance: somma diretta delle 1X2 (senza griglia) contro la griglia

| de-vig | doppia chance | |Δ| mediana | |Δ| media | p95 | differenza MASSIMA |Δ| |
|---|---|---|---|---|---|
| proporzionale | 1X | 1.1e-16 | 2.3e-15 | 1.1e-15 | **7.4e-13** |
| proporzionale | X2 | 1.1e-16 | 2.0e-15 | 8.9e-16 | **7.3e-13** |
| proporzionale | 12 | 2.2e-16 | 4.0e-15 | 1.7e-15 | **1.5e-12** |
| potenza | 1X | 1.1e-16 | 1.9e-15 | 1.1e-15 | **9.9e-13** |
| potenza | X2 | 1.1e-16 | 1.4e-15 | 7.8e-16 | **1.0e-12** |
| potenza | 12 | 2.2e-16 | 3.1e-15 | 1.7e-15 | **2.0e-12** |
| Shin | 1X | 1.1e-16 | 1.7e-15 | 1.1e-15 | **6.8e-13** |
| Shin | X2 | 1.1e-16 | 1.3e-15 | 8.8e-16 | **5.4e-13** |
| Shin | 12 | 2.2e-16 | 2.7e-15 | 1.8e-15 | **1.2e-12** |

Δ = (p₁ + pX dalla terna de-vigata) − P(doppia chance) dalla griglia, in frazione di probabilità (1e-16 = una unità di macchina). La somma diretta è calcolata SENZA griglia: P(1X) = p₁ + pX, P(X2) = pX + p₂, P(12) = p₁ + p₂.

**Le due vie coincidono al livello di macchina, con ogni de-vig.** Non è un caso: il fit vincola la griglia a riprodurre ESATTAMENTE la terna 1X2 (3 parametri, 3 vincoli indipendenti, residuo massimo ~1e-12) e 1X, X2 e 12 sono unioni di celle 1X2 (1X = «1» ∪ «X», X2 = «X» ∪ «2», 12 = «1» ∪ «2»), quindi la loro probabilità è la somma delle tre di partenza qualunque cosa faccia il modello dentro le celle: la differenza massima è solo l'errore di arrotondamento in virgola mobile. La conseguenza pratica è che sulla doppia chance la griglia NON aggiunge nulla al de-vig: al contrario di Over 1,5, Over 3,5, Gol e delle combinazioni (1+Over 1,5, 1X+Over 1,5, 1X+Under 3,5), dove il valore dipende da come la massa è distribuita dentro la griglia.

### 2.5 Limiti

- Campione unico (3.504 partite B365, due stagioni): i conti per fascia non sono indipendenti fra mercati derivati dalla stessa griglia.
- Il de-vig e' applicato sia alla terna 1X2 sia all'Over/Under 2,5: i due effetti non sono separati in questa tabella.
- R4 non e' una misura di valore economico: dice solo se la frequenza osservata e' compatibile con la probabilita' dichiarata.
- «Non valutabile» (nessuna fascia con n ≥ 100) e' una lettura conservativa: il mercato resta fuori (regola di PR #59, non modificata).

## 3. Punto 3 — diagnosi della sonda totals (sui file grezzi, offline)

Generato da `audit/totals_probe_diagnosi.py` il 2026-10-10T19:25:30Z dai 5 snapshot grezzi in `audit/data/totals_probe/`. Nessuna chiamata di rete, nessuna chiave, nessuna nuova richiesta a The Odds API.

Eventi totali: **82** · superano la regola: **56** (68,3 %) · non la superano: **26** (31,7 %). Soglia dell'85 %: **NON superata** (come in PR #59). Solo descrittivo: nessuna conseguenza sul codice.

### 3.1 I 26 eventi che non superano la regola, per causa

Causa assegnata per priorità (D2): C1 Pinnacle assente → C2 Pinnacle con linea ≠ 2,5 → C3 Pinnacle 2,5 con meno di 3 libri → C4 altro. Poiché la regola è un OR, tutti i 26 hanno anche meno di 3 libri con la 2,5: il conteggio per numero di libri è sotto.

| causa | eventi |
|---|---|
| C1 Pinnacle assente | 2 |
| C2 Pinnacle con linea 1,5 | 1 |
| C2 Pinnacle con linea 3,5 | 5 |
| C2 Pinnacle con linea a quarti | 12 |
| C2 Pinnacle con linea altra mezza | 2 |
| C2 Pinnacle con linea intera | 4 |

| lega | eventi | superano la regola | non la superano | C1 Pinnacle assente | C2 Pinnacle con linea 1,5 | C2 Pinnacle con linea 3,5 | C2 Pinnacle con linea a quarti | C2 Pinnacle con linea altra mezza | C2 Pinnacle con linea intera |
|---|---|---|---|---|---|---|---|---|---|
| Premier League | 17 | 13 | 4 | 2 | 0 | 1 | 0 | 0 | 1 |
| Ligue 1 | 17 | 13 | 4 | 0 | 1 | 0 | 3 | 0 | 0 |
| Bundesliga | 12 | 2 | 10 | 0 | 0 | 3 | 3 | 2 | 2 |
| Serie A | 19 | 16 | 3 | 0 | 0 | 0 | 2 | 0 | 1 |
| La Liga | 17 | 12 | 5 | 0 | 0 | 1 | 4 | 0 | 0 |
| **totale** | 82 | 56 | 26 | 2 | 1 | 5 | 12 | 2 | 4 |

#### 3.1.1 Linea di Pinnacle nei 26 eventi (quando presente)

| linea Pinnacle | eventi |
|---|---|
| 1,5 | 1 |
| 3,5 | 5 |
| a quarti | 12 |
| altra mezza | 2 |
| assente | 2 |
| intera | 4 |

Valori esatti della linea Pinnacle nei 26 eventi: **1.5** × 1, **3.0** × 4, **3.25** × 6, **3.5** × 5, **3.75** × 5, **4.5** × 2, **4.75** × 1.

#### 3.1.2 Quanti libri offrono la 2,5 nei 26 eventi

| libri con la linea 2,5 | eventi |
|---|---|
| 0 | 5 |
| 1 | 0 |
| 2 | 21 |

C3 è vuota **per costruzione**: se Pinnacle ha la 2,5 la regola è soddisfatta, quindi un evento che non la supera non può avere Pinnacle a 2,5.

### 3.2 Giorni mancanti al calcio d'inizio al momento della chiamata

| misura | giorni |
|---|---|
| n | 82 |
| minimo | -0,08 |
| p10 | 0,07 |
| p25 | 0,92 |
| mediana | 6,85 |
| p75 | 7,83 |
| p90 | 8,07 |
| massimo | 13,98 |
| media | 4,97 |

| fascia di giorni mancanti | eventi | quota |
|---|---|---|
| < 0 (già iniziata) | 5 | 6,1 % |
| [0-1) | 20 | 24,4 % |
| [1-2) | 4 | 4,9 % |
| [2-7) | 24 | 29,3 % |
| [7-14) | 29 | 35,4 % |
| ≥ 14 | 0 | 0,0 % |

| lega | eventi | minimo | mediana | massimo |
|---|---|---|---|---|
| Premier League | 17 | -0,02 | 6,87 | 13,98 |
| Ligue 1 | 17 | -0,08 | 6,07 | 8,07 |
| Bundesliga | 12 | -0,02 | 6,85 | 7,93 |
| Serie A | 19 | -0,04 | 6,07 | 9,07 |
| La Liga | 17 | -0,02 | 6,79 | 9,08 |

### 3.3 Stessa classificazione separata: entro 7 giorni e oltre 7 giorni

| gruppo | eventi | superano la regola | quota | non la superano |
|---|---|---|---|---|
| entro 7 giorni | 53 | 32 | 60,4 % | 21 |
| oltre 7 giorni | 29 | 24 | 82,8 % | 5 |
| **tutti** | 82 | 56 | 68,3 % | 26 |

Causa degli eventi che non superano la regola, nei due gruppi:

| gruppo | non superano | C1 Pinnacle assente | C2 Pinnacle con linea 1,5 | C2 Pinnacle con linea 3,5 | C2 Pinnacle con linea a quarti | C2 Pinnacle con linea altra mezza | C2 Pinnacle con linea intera |
|---|---|---|---|---|---|---|---|
| entro 7 giorni | 21 | 0 | 1 | 3 | 11 | 2 | 4 |
| oltre 7 giorni | 5 | 2 | 0 | 2 | 1 | 0 | 0 |

«Entro 7 giorni» = giorni mancanti ≤ 7 (comprese le partite gia' iniziate al momento della chiamata); «oltre 7 giorni» = giorni mancanti > 7. Lettura solo descrittiva: la quota dell'85 % non e' raggiunta in nessuno dei due gruppi.

### 3.4 Costo reale della sonda in crediti (dagli header)

| # (ordine di tempo) | sport_key | fetched_at_utc | x-requests-last (costo) | x-requests-used | x-requests-remaining | eventi |
|---|---|---|---|---|---|---|
| 1 | soccer_italy_serie_a | 2026-10-10T17:03:43Z | 1 | 59 | 441 | 19 |
| 2 | soccer_epl | 2026-10-10T17:03:43Z | 1 | 60 | 440 | 17 |
| 3 | soccer_spain_la_liga | 2026-10-10T17:03:43Z | 1 | 61 | 439 | 17 |
| 4 | soccer_germany_bundesliga | 2026-10-10T17:03:44Z | 1 | 62 | 438 | 12 |
| 5 | soccer_france_ligue_one | 2026-10-10T17:03:44Z | 1 | 63 | 437 | 17 |

**Crediti spesi nel run: 5** (una chiamata per lega, 5 chiamate). Stato finale (ultima chiamata in ordine di tempo, `soccer_france_ligue_one` alle 2026-10-10T17:03:44Z): **used = 63, remaining = 437**. Stato prima del run (prima chiamata, `soccer_italy_serie_a`): used = 59, remaining = 441.

**Correzione dello stato finale.** `audit/results/totals_probe_analysis.md` riporta «used=61, remaining=439»: è lo stato della chiamata `soccer_spain_la_liga`, l'ULTIMA LEGA IN ORDINE ALFABETICO, non l'ultima chiamata in ordine di tempo. Con la chiave (`fetched_at_utc`, `x-requests-used`) l'ultima chiamata è `soccer_france_ligue_one` (usati 63, residui 437). La correzione è stata applicata in `audit/totals_probe_analysis.py` (funzione `ordine_cronologico` + scelta dello stato finale) e in `audit/totals_probe.py` (stato finale preso per max della stessa chiave, non dall'ultima lega del ciclo). Il numero di crediti spesi (5) non cambia: cambia lo stato del conto attribuito al run.

### 3.5 Limiti

- La sonda misura la DISPONIBILITÀ delle linee totals, non le quote Over/Under: le quote sono nel corpo grezzo e qui non sono state usate (solo nel punto 4, per il confronto fra griglie).
- Una linea per libro e per evento: se un libro offre più linee se ne tiene la più bassa, come in `totals_probe_analysis.py`.
- L'ora della chiamata è `fetched_at_utc` (risoluzione 1 secondo): i giorni mancanti hanno quindi un'incertezza dell'ordine del secondo, irrilevante sulle fasce usate.
- Lo snapshot è unico (2026-10-10): la relazione fra giorni mancanti e disponibilità della 2,5 è misurata su 82 eventi di una sola giornata tipo ed è descrittiva, non una stampa di un effetto.

## 4. Punto 4 — fit della griglia su una linea totals qualunque

Generato da `audit/linee_totali_probe.py` il 2026-10-10T19:37:34Z · linee e quote totals dalla sonda in `audit/data/totals_probe/` (2026-10-10T17:03Z) · terna 1X2 Pinnacle da `SoccerMath/database/live_odds.json` (2026-10-10T09:08:52Z) · nessuna nuova chiamata a The Odds API, nessuna chiave, nessuna modifica a `SoccerMath/`.

### 4.1 Estensione del fit (audit/griglia_core.py)

Il terzo vincolo del fit non è più la sola P(Over 2,5) ma la **probabilità giusta** di una linea qualsiasi, calcolata con le regole di pagamento del mercato:

| tipo di linea | regola | probabilità giusta usata nel fit |
|---|---|---|
| mezza (1,5 / 2,5 / 3,5) | vinta sopra la linea, persa sotto | P(gol totali > linea) |
| intera (2 / 3) | rimborso se i gol totali sono uguali alla linea | P(sopra) / (1 − P(uguale)) |
| a quarti (2,25 / 2,75) | mezza puntata su ciascuna delle due linee adiacenti | quota equa da EV nullo: p = W / (W + Lp) |

`W` = frazione di puntata che vince, `Lp` = frazione che perde, il resto è rimborsato. Con questa definizione p(sopra) + p(sotto) = 1 per ogni tipo di linea, quindi il de-vig a due vie è applicabile senza correzioni. Test di andata e ritorno su parametri noti per ogni tipo di linea: `audit/test_griglia_core_linee.py` (81 test; 96 in tutto insieme a `audit/test_griglia_core.py` e `audit/test_griglia_varianti.py`), residuo richiesto < 1e-9 e quote eque verificate con tabelle di profitto scritte a mano.

### 4.2 Verifica su dati reali

Eventi della sonda: **82**. Eventi con la terna 1X2 Pinnacle disponibile: **77** (aggancio per `id`). Eventi **confrontabili** (Pinnacle con linea ≠ 2,5 e almeno 3 altri libri con la 2,5): **42**.

| partita | lega | linea Pinnacle | tipo | libri a 2,5 | P(Over 2,5) A / B (%) | Δ Over 2,5 (pt) | Δ Gol (pt) | Δ Over 1,5 (pt) | residuo A |
|---|---|---|---|---|---|---|---|---|---|
| Manchester United – Tottenham Hotspur | Premier League | 2.25 | a quarti | 5 | 44.49 / 39.95 | 4.54 | 4.33 | 4.41 | 3e-17 |
| Parma – Torino | Serie A | 2 | intera | 8 | 38.70 / 42.08 | 3.38 | 3.23 | 3.41 | 6e-17 |
| Frosinone – Sassuolo | Serie A | 3 | intera | 6 | 61.45 / 58.70 | 2.76 | 2.41 | 2.05 | 1e-16 |
| Sassuolo – AC Milan | Serie A | 2.75 | a quarti | 13 | 54.90 / 53.33 | 1.57 | 1.41 | 1.26 | 1e-16 |
| Torino – Udinese | Serie A | 2.25 | a quarti | 14 | 43.71 / 45.14 | 1.44 | 1.34 | 1.35 | 6e-17 |
| Lyon – Nice | Ligue 1 | 2.75 | a quarti | 9 | 57.45 / 56.02 | 1.43 | 1.30 | 1.10 | 6e-17 |
| Nice – Strasbourg | Ligue 1 | 2.75 | a quarti | 10 | 57.31 / 55.89 | 1.43 | 1.25 | 1.11 | 1e-16 |
| Tottenham Hotspur – Coventry City | Premier League | 3 | intera | 8 | 61.16 / 59.74 | 1.41 | 1.31 | 1.03 | 1e-16 |
| FC Schalke 04 – FSV Mainz 05 | Bundesliga | 3 | intera | 10 | 60.66 / 59.25 | 1.41 | 1.23 | 1.05 | 2e-16 |
| Brest – Angers | Ligue 1 | 2.75 | a quarti | 10 | 57.99 / 56.58 | 1.41 | 1.25 | 1.09 | 0e+00 |
| Troyes – Marseille | Ligue 1 | 3 | intera | 8 | 60.96 / 59.62 | 1.35 | 1.19 | 0.99 | 1e-16 |
| Leeds United – Manchester United | Premier League | 3 | intera | 10 | 58.88 / 57.56 | 1.32 | 1.16 | 1.01 | 6e-17 |
| Real Racing Club de Santander – Valencia | La Liga | 2.75 | a quarti | 11 | 56.97 / 55.70 | 1.27 | 1.12 | 1.00 | 6e-17 |
| Lecce – Bologna | Serie A | 2.25 | a quarti | 12 | 44.04 / 45.27 | 1.22 | 1.14 | 1.14 | 6e-17 |
| Fiorentina – Como | Serie A | 2.75 | a quarti | 9 | 57.45 / 56.28 | 1.17 | 1.03 | 0.91 | 1e-16 |
| Venezia – Napoli | Serie A | 2.75 | a quarti | 10 | 56.64 / 55.53 | 1.12 | 1.01 | 0.87 | 6e-17 |
| Bologna – Inter Milan | Serie A | 2.75 | a quarti | 10 | 57.79 / 56.75 | 1.04 | 0.95 | 0.80 | 0e+00 |
| Getafe – Rayo Vallecano | La Liga | 2 | intera | 8 | 37.83 / 38.65 | 0.82 | 0.80 | 0.86 | 6e-17 |
| Brighton and Hove Albion – Crystal Palace | Premier League | 3 | intera | 9 | 61.35 / 60.56 | 0.79 | 0.72 | 0.58 | 1e-16 |
| Como – AS Roma | Serie A | 3 | intera | 10 | 59.20 / 58.46 | 0.74 | 0.65 | 0.56 | 1e-16 |
| Fulham – Hull City | Premier League | 2.75 | a quarti | 11 | 54.54 / 55.28 | 0.74 | 0.67 | 0.59 | 6e-17 |
| Monza – Cagliari | Serie A | 2.25 | a quarti | 9 | 46.21 / 45.68 | 0.54 | 0.50 | 0.49 | 1e-16 |
| Paris FC – Rennes | Ligue 1 | 2.75 | a quarti | 9 | 57.79 / 57.29 | 0.50 | 0.44 | 0.39 | 6e-17 |
| Real Sociedad – Deportivo La Coruña | La Liga | 2.75 | a quarti | 12 | 55.25 / 54.77 | 0.48 | 0.44 | 0.38 | 1e-16 |
| Levante – Sevilla | La Liga | 2.25 | a quarti | 12 | 46.35 / 46.79 | 0.44 | 0.41 | 0.40 | 6e-17 |
| Newcastle United – Aston Villa | Premier League | 3 | intera | 11 | 59.57 / 59.18 | 0.39 | 0.34 | 0.29 | 6e-17 |
| Lille – Brest | Ligue 1 | 2.75 | a quarti | 9 | 56.76 / 57.14 | 0.39 | 0.35 | 0.30 | 1e-16 |
| Everton – Chelsea | Premier League | 2.75 | a quarti | 11 | 57.68 / 58.06 | 0.38 | 0.34 | 0.29 | 6e-17 |
| CA Osasuna – Real Racing Club de Santander | La Liga | 2.75 | a quarti | 9 | 53.96 / 54.32 | 0.37 | 0.33 | 0.30 | 6e-17 |
| AS Monaco – Toulouse | Ligue 1 | 3 | intera | 8 | 60.96 / 60.62 | 0.34 | 0.31 | 0.25 | 1e-16 |
| SC Freiburg – FC Schalke 04 | Bundesliga | 2.75 | a quarti | 11 | 58.44 / 58.14 | 0.30 | 0.27 | 0.23 | 3e-17 |
| Espanyol – Atlético Madrid | La Liga | 2.75 | a quarti | 10 | 53.37 / 53.58 | 0.21 | 0.19 | 0.17 | 6e-17 |
| Coventry City – Newcastle United | Premier League | 2.75 | a quarti | 12 | 56.97 / 56.78 | 0.19 | 0.17 | 0.15 | 6e-17 |
| Le Mans FC – Toulouse | Ligue 1 | 2.75 | a quarti | 10 | 54.19 / 54.38 | 0.19 | 0.17 | 0.15 | 1e-16 |
| Angers – Marseille | Ligue 1 | 3 | intera | 9 | 59.77 / 59.95 | 0.18 | 0.16 | 0.13 | 6e-17 |
| Liverpool – Manchester City | Premier League | 3 | intera | 10 | 59.49 / 59.67 | 0.17 | 0.15 | 0.13 | 6e-17 |
| Troyes – RC Lens | Ligue 1 | 3 | intera | 9 | 60.86 / 60.76 | 0.10 | 0.09 | 0.07 | 6e-17 |
| Celta Vigo – Alavés | La Liga | 2.25 | a quarti | 9 | 44.92 / 44.97 | 0.06 | 0.06 | 0.06 | 6e-17 |
| AS Roma – Genoa | Serie A | 2.75 | a quarti | 9 | 57.79 / 57.84 | 0.05 | 0.05 | 0.04 | 2e-16 |
| AC Milan – Atalanta BC | Serie A | 2.75 | a quarti | 9 | 54.42 / 54.38 | 0.05 | 0.04 | 0.04 | 6e-17 |
| Málaga – Real Sociedad | La Liga | 2.75 | a quarti | 9 | 53.84 / 53.81 | 0.04 | 0.03 | 0.03 | 1e-16 |
| Real Betis – CA Osasuna | La Liga | 2.75 | a quarti | 12 | 54.44 / 54.42 | 0.02 | 0.02 | 0.02 | 6e-17 |

Differenze fra la griglia A (linea Pinnacle, fit generalizzato) e la griglia B (linea 2,5 degli altri libri), in valore assoluto:

| mercato | n | mediana | massimo |
|---|---|---|---|
| P(Over 2,5) | 42 | 0.64 pt | 4.54 pt |
| P(Gol) | 42 | 0.57 pt | 4.33 pt |
| P(Over 1,5) | 42 | 0.53 pt | 4.41 pt |

**Esito della regola dichiarata (P4.4): NON utilizzabile.** Mediana 0.64 pt (soglia ≤ 1.5) e massimo 4.54 pt (soglia ≤ 4) su 42 eventi.


### 4.3 Conteggio: quanti eventi avrebbero una linea utilizzabile

Linea utilizzabile = almeno una linea totals di un tipo gestito dal fit (mezza, intera o a quarti) da almeno un bookmaker, **e** la terna 1X2 Pinnacle per lo stesso evento (senza 1X2 il fit non esiste). Solo conteggio: l'ingresso di totals in produzione si decide su una sonda nuova.

| misura | tutti gli eventi | entro 7 giorni |
|---|---|---|
| eventi della sonda | 82 | 53 |
| con almeno una linea totals di tipo gestito | 82 | — |
| con la terna 1X2 Pinnacle | 77 | — |
| **con una linea UTILIZZABILE (entrambi)** | **77** | **51** |

Linee esposte da Pinnacle sugli 82 eventi (valori grezzi): **1.5** × 1, **2.0** × 2, **2.25** × 6, **2.5** × 14, **2.75** × 22, **3.0** × 16, **3.25** × 6, **3.5** × 5, **3.75** × 5, **4.5** × 2, **4.75** × 1; Pinnacle assente: 2.


### 4.4 Limiti

- La terna 1X2 viene da uno snapshot **8 ore prima** della sonda totals (`live_odds.json` 2026-10-10T09:08:52Z contro 2026-10-10T17:03Z): le quote 1X2 nel frattempo hanno potuto muoversi. La differenza misurata fra A e B include questo disallineamento, che agisce però nella stessa direzione sulle due griglie (la terna è identica).
- Snapshot unico: 42 eventi confrontabili su 82. Con meno di 10 eventi la regola dichiara «non decidibile», che è l'esito atteso su una sola giornata tipo.
- Il consenso 2,5 e' la mediana delle P(Over 2,5) de-vigate dei libri: libri con margini molto diversi pesano tutti allo stesso modo.
- De-vig proporzionale su tutte le fonti (P4.3): la scelta del de-vig non è oggetto di questo punto (lo è del punto 1).
- Nessuna conseguenza sulla produzione: totals non entra in produzione con questo audit e la regola dell'85% della PR #59 resta non superata.

## 5. Chiusura

### 5.1 Suite completa (output reale, locale, stessi comandi del workflow `test_suite.yml`)

Eseguita il 2026-10-10 con lo stesso ambiente dichiarato dai workflow
(`pip install -r SoccerMath/requirements.txt -r requirements-audit.txt pytest`,
Python 3.11, numpy 2.4.6, pandas 3.0.6, scipy 1.17.1, streamlit 1.65.0, pytest 9.1.1),
sui **93** file `test_*.py` (i 91 già tracciati + `audit/test_griglia_core_linee.py` +
`audit/test_totals_probe_diagnosi.py`), più `SoccerMath/test_theme_toggle.py` come script.
Log completo: `/tmp/suite-out2/pytest.log`; coda salvata in
`audit/results/suite_completa_2026-10-10_devig_linee.log`.

```
=============================== warnings summary ===============================
audit/test_elo_w025_confirmation.py::TestPatchGriglia::test_boot_stats_delta_vs_060_con_griglia_ridotta
  /home/user/SoccerMath2.0/audit/grid_search_ensemble_weight.py:224: RuntimeWarning: invalid value encountered in divide
    rr = np.where(staked > 0, prof / staked, np.nan)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
1967 passed, 1 warning, 4773 subtests passed in 237.54s (0:03:57)
PYTEST_EXIT=0
```

`test_theme_toggle.py` (come script):

```
✅ Run 1 OK - toggle ON (segue tema sistema), nessuna eccezione
✅ Run 2 OK - toggle OFF, CSS light forzato presente (2 blocchi <style>)
✅ Run 3 OK - ritorno a ON, CSS forzato rimosso, nessuna eccezione
✅ Run 4 OK - rerun generico senza crash

🎉 TUTTI I TEST PASSATI: nessun crash in nessuno stato del toggle.
THEME_EXIT=0
```

Nota: la suite PR #59 contava 1866 test; qui 1967 (+101: test nuovi del punto 4 e del punto 3).
Nota sul clone: il checkout della sandbox era *shallow*; 10 test di provenienza
(`test_elo_probs_equivalence.py`, `test_elo_s3_parity.py`, `test_elo_walker_parity.py`,
`test_reconstruct_topmix_match.py`) fallivano perché cercano commit storici non presenti in un
clone shallow. Risolto con `git fetch --unshallow` (nessuna modifica ai file); in CI i workflow
fanno checkout con `fetch-depth: 0` e questi test passano (vedi sotto).

### 5.2 Esito CI per workflow (PR #60, commit `cf1d32b`)

Step per step da `gh api repos/iFelice/SoccerMath2.0/actions/runs/<id>/jobs`:

- **`Suite test completa`** (run 38081172459): **success**. Step: Checkout (storia completa),
  Salta?, Set up Python, Dipendenze, Diagnostica del runner, Elenco dei file di test,
  **Suite pytest (tutti i file test_*.py tracciati): success**, test_theme_toggle.py come script:
  success, Riepilogo e annotazioni, artifact. Nessun passo saltato.
- **`Audit Top Mix (sola lettura)`** (run 38081172460): **success**. Step: Salta?, Dipendenze,
  Test diagnostici Top Mix ed Elo: success, **Replay offline del Top Mix di mercato
  (topmix_mercato_v3): success**, GET JSONBin Schalke–Bayern (sola lettura): success,
  Ricostruzione Schalke–Bayern: success, Ispezione tracciamento Registro (AST): success,
  **Nessuna modifica ai dati/codice di produzione: success**. Nessun passo saltato.
- **`Replay Top Mix legacy (walk-forward, no-leakage)`** (run 38081172462): **success**, ma
  **tutti gli step di replay sono `skipped`**: l'unico passo eseguito è «File rilevanti per il
  replay», che stabilisce che questa PR non tocca file rilevanti per il replay legacy
  (stesso comportamento della PR #59). Questo run quindi non esegue il replay legacy e non ne è
  una verifica.

Tutti e tre i workflow sono **success anche sul commit finale `c773551`** (run 38081683984, 38081684017 e replay legacy): il confronto «Salta?» è fatto contro la base della PR (`origin/main`) e il branch contiene i `.py` dell'audit, quindi la regola docs-only non scatta neppure sul commit che aggiorna solo questo referto. Sul commit finale la Suite pytest e il replay offline `topmix_mercato_v3` sono stati eseguiti di nuovo: entrambi success.

**Limite (come PR #59):** i log testuali (`gh run view --log`) e gli artifact
(`suite-test-38081172459`, …) non sono scaricabili dalla sandbox: errore `EOF` dal backend
`results-receiver.actions.githubusercontent.com` / blob storage. I conteggi del replay e della
suite in CI non sono quindi leggibili qui; gli esiti sono verificati a livello di step (API) e i
numeri riportati in §5.1 e §5.3 sono locali, prodotti con gli stessi comandi.

### 5.3 Replay `topmix_mercato_v3` (output reale, senza `--write`, output in `/tmp/replay/`)

```
| Voce           | n PR #49 | n replay | Δn | hit PR #49 | hit replay | Δhit   | coincide |
|----------------|----------|----------|----|------------|------------|--------|----------|
| scelte_mercato |     1302 |     1302 | +0 |     0.6751 |     0.6751 | +0.0000 | SÌ      |
| accordo        |     1144 |     1144 | +0 |     0.6818 |     0.6818 | +0.0000 | SÌ      |
| senza_accordo  |      335 |      335 | +0 |     0.4358 |     0.4358 | +0.0000 | SÌ      |

Esito del confronto: PARITÀ (tolleranze dichiarate: Δn ≤ 0, |Δhit| ≤ 0.0005).
```

Conteggi **1302 / 1144 / 335, Δn = 0** su tutte e tre le voci (parità con PR #49 e PR #59).
Nessuna scrittura nel Registro: il replay è girato con `--json/--report/--righe` in `/tmp/replay/`.
Coerenza con il punto 1.7: sul campione B365 il de-vig proporzionale dà 1302 scelte con hit rate
67,51 %, identiche a quelle del replay (stessa regola di argmax e soglia 0,55).

### 5.4 Esiti in breve

- **Punto 1.** La regola dichiarata NON propone il passaggio alla potenza: sul campione primario
  (2022/23 + 2023/24, Pinnacle pre-chiusura, n = 3536) l'IC 95 % di ΔLogLoss(potenza −
  proporzionale) è [−0,001106; +0,000091] e contiene lo zero. Resta il **proporzionale**.
  (Segnale descrittivo: Shin ha IC interamente sotto zero sul primario [−0,000920; −0,000084] e
  sulla conferma [−0,001216; −0,000084], ma la regola valuta Shin solo dopo la potenza; la
  decisione resta «proporzionale».) Sulle 3.504 partite, potenza e Shin fanno entrare 163 e 105
  scelte in più (nessun cambio di esito, nessuna uscita: i tre metodi sono trasformazioni
  monotone della stessa terna); l'hit rate delle scelte aggiuntive è 56,4 % e 53,3 %, sotto il
  67,5 % delle scelte del proporzionale.
- **Punto 2.** Con potenza/Shin i tre mercati fuori lista di PR #59 (X2, 1+Over 1,5, 1X+Over 1,5)
  riducono lo scarto f − p ed entrano nella lista R4; Gol al contrario esce con Shin (fascia
  0,65-0,75: −8,1 pt, IC sotto zero). Lo scarto quindi **cambia col metodo** e cambiano gli
  esiti di 4 mercati su 11. La doppia chance diretta dalla somma delle 1X2 coincide con la
  griglia al livello di macchina (max 2e-12): sulla doppia chance il modello non aggiunge nulla
  al de-vig. Parità con la tabella PR #59 sul proporzionale: n identici, scarto massimo su f − p
  0,04 pt (arrotondamento del referto PR #59).
- **Punto 3.** Dei 26 eventi fuori regola: 2 senza Pinnacle, 24 con Pinnacle su altra linea
  (12 a quarti, 5 a 3,5, 4 intere, 2 altra mezza, 1 a 1,5); C3 vuota per costruzione. Entro 7
  giorni la regola è al 60,4 %, oltre 7 giorni all'82,8 %: nessuna delle due supera l'85 %.
  Costo della sonda: 5 crediti; stato finale corretto **63/437** (era 61/439, stato dell'ultima
  lega alfabetica). Correzione applicata in `totals_probe.py` e `totals_probe_analysis.py` con
  test di regressione.
- **Punto 4.** Il fit generalizzato recupera i parametri noti al livello di macchina su tutti i
  tipi di linea (96 test). Sui dati reali (42 eventi confrontabili ≥ 10): differenza mediana su
  P(Over 2,5) **0,64 pt** (≤ 1,5) ma massima **4,54 pt** (> 4), un solo evento sopra soglia
  (Manchester United–Tottenham, linea Pinnacle 2,25 contro 2,5 degli altri libri): esito
  dichiarato **NON utilizzabile su questo snapshot**. Linee utilizzabili: 77/82 eventi
  (51/53 entro 7 giorni), solo conteggio.

### 5.5 Elenco di ciò che non è stato verificato

- Quote storiche B365 e Pinnacle dei CSV: non confrontate con The Odds API (il piano gratuito non
  include lo storico), come PR #58/#59.
- L'1X2 usato nel punto 4 viene da uno snapshot di 8 ore precedente alla sonda totals
  (`live_odds.json` 2026-10-10T09:08Z contro 17:03Z): lo spostamento delle quote in quelle ore
  non è misurabile da questo snapshot.
- L'esito del punto 4 è su un singolo snapshot di una giornata tipo: la regola «NON utilizzabile»
  dipende da 1 evento su 42 (4,54 pt contro soglia 4) e non è una stima stabile nel tempo; va
  ripetuta su una sonda nuova, come già previsto per l'ingresso di totals in produzione.
- Il costo della sonda «in crediti» è quello dichiarato dagli header; il piano tariffario di The
  Odds API non è verificato oltre gli header stessi.
- Log e artifact CI non scaricabili dalla sandbox (errore EOF): gli esiti CI sono verificati solo
  a livello di step; i conteggi della suite e del replay in CI non sono letti (numeri locali in
  §5.1 e §5.3).
- Suite completa eseguita localmente con gli stessi comandi del workflow, non sul runner GitHub
  (il runner CI ha comunque passato la stessa suite: §5.2).
- Punto 1: la conferma 2024/25 + 2025/26 è troncata a metà gennaio 2026 per la copertura
  Pinnacle dei CSV (dichiarato in §1.1); il Brier è multiclasse e secondario; il LogLoss è
  limitato sotto a 1e-12 (nessuna probabilità osservata si avvicina).
- Punto 2: il de-vig è applicato sia alla terna sia all'Over/Under 2,5; i due effetti non sono
  separati; la calibrazione non misura il valore economico delle giocate.
- Punto 3: le partite già iniziate al momento della chiamata (giorni < 0) restano nel gruppo
  «entro 7 giorni» (dichiarato in §0.3/D3).
- Nessuna verifica del comportamento di Shin/potenza su quote live reali (non nel repository);
  i metodi sono testati su quote storiche e su casi sintetici.
- Dixon & Coles (1997) fonte primaria: già dichiarata non accessibile in PR #59 (paywall); questo
  audit riusa la convenzione tau già stabilita e non la ri-verifica.

### 5.6 Vincoli rispettati

- Nessuna modifica a `SoccerMath/` né a `app.py` (`git diff --stat -- SoccerMath/` vuoto).
- Nessun `--write` e nessuna scrittura nel Registro; il replay gira con output in `/tmp/replay/`.
- Nessuna nuova chiamata a The Odds API: i punti 3 e 4 leggono solo i file grezzi già in
  `audit/data/totals_probe/` e `SoccerMath/database/live_odds.json`; gli script nuovi non hanno
  codice di rete.
- La chiave The Odds API non compare in nessun output, log o file (gli snapshot hanno
  `apiKey=***`; verificato anche nei test `test_totals_probe*.py`).
- Le regole dei punti 1 e 4 sono scritte in §0 prima dei numeri e non sono state modificate dopo.

