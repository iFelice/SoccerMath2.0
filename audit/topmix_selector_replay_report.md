# Confronto A vs B del selettore Top Mix — esecuzione del protocollo §4.1

**Esito in una riga: il confronto NON è positivo per B, quindi il cambio di
selettore non viene proposto e non c'è nessun commit che tocca `app.py`.**

Documento di risultato. Il protocollo di riferimento è
[`audit/topmix_selector_audit_protocol.md`](topmix_selector_audit_protocol.md);
i numeri completi (per lega, per stagione, per lega×stagione) sono in
[`audit/results/topmix_selector_replay.md`](results/topmix_selector_replay.md)
e in `audit/results/topmix_selector_replay.json`; le righe per-partita in
`audit/results/topmix_selector_replay_rows.csv`.

---

## 0. Cosa è stato eseguito, e con quali dati

Harness: `audit/topmix_selector_replay.py` (sola lettura).
Test dell'harness: `audit/test_topmix_selector_replay.py` (17 test).

| Pezzo | Come | Nota |
|---|---|---|
| Selettore A | `apply_selector_A` (trascrizione di `fetch_and_calc_top_mix`) | argmax Poisson → Elo solo sul mercato scelto → filtri sull'intera partita |
| Selettore B | `apply_selector_B` (già in `reconstruct_topmix_match.py`) | confidence finale su tutti e 7 i mercati → filtri per mercato → massimo ammissibile |
| Giornata | `select_next_matchday_matches` di produzione, `now` esplicito | `now` = primo kickoff della giornata − 1 s; finestra `TOP_MIX_ROUND_WINDOW_DAYS=5` |
| Motore | `get_league_engine` + `get_full_poisson_two_heads` | due teste, `PRIOR_MATCHES=6`, forma solo in 1X2 |
| Elo | `predict_elo_probs` (`models/elo_engine.py`) | home advantage per lega, ricalcolato sui CSV troncati |
| Dati | point-in-time: CSV con kickoff `< cutoff`; xG da `xg_archive.season_averages(cutoff_policy="previous_day")` | scritti in una tmpdir; **il database di produzione non è stato toccato** |
| Soglie/pesi | 0.55 / 0.60 / 0.25, 0.6/0.4, top 10 | **importati**, mai ridefiniti: nessun grid-search |

**Etichetta obbligatoria delle stagioni.** 2024/25 e 2025/26 sono
**validation storica già esaminata**: sono le stagioni su cui sono già stati
scelti Poisson a due teste, forma fuori dai totali, `PRIOR_MATCHES=6` ed è
stato confermato l'ensemble 0.6/0.4. **Non sono un test intatto** e nel report
non vengono chiamate così. L'unica via non contaminata resta la conferma
prospettica 2026/27 in poi, che richiede prima il tracciamento.

Perimetro: 5 leghe × 2 stagioni, **384 giornate ricostruite**, **3 422 partite
candidate** su 3 504 a calendario (82 mai candidate: recuperi giocati mentre la
giornata dopo era già la "prossima"; 87 escluse dalla finestra di round).
Una sola osservazione per `match_id` (0 duplicati da scartare).

---

## 1. Frequenza di disaccordo sul mercato

Non "esiste un caso", ma quanto spesso:

| | conteggio | frequenza |
|---|---:|---:|
| Partite dove **entrambi** mostrano una riga | 1 865 | — |
| …di cui con **mercato diverso** | **74** | **4,0 %** |
| Partite candidate dove ciò che B mostrerebbe ≠ argmax Poisson di A | 229 | 6,7 % |

Per lega (mercato diverso / entrambi ammessi): Bundesliga 29/419 = 6,9 %,
Premier 23/422 = 5,5 %, Serie A 10/363 = 2,8 %, Ligue 1 8/281 = 2,8 %,
La Liga 4/380 = 1,1 %.
Per stagione: 2024/25 43/935 = 4,6 %; 2025/26 31/930 = 3,3 %.

Il disaccordo è **raro**: nel 96 % dei casi in cui entrambi mostrano qualcosa,
mostrano lo stesso mercato con la stessa probabilità.

---

## 2. Sulle partite in disaccordo: chi ha ragione

Ciascun selettore valutato sull'evento che ha selezionato lui, con la
probabilità che avrebbe mostrato.

| n = 74 | prob media | hit rate | Brier |
|---|---:|---:|---:|
| **A** | 61,4 % | **66,2 %** | **0,2225** |
| **B** | 64,6 % | 56,8 % | 0,2528 |
| Δ (A−B) | +3,2 pp mostrata in meno | **+9,5 pp di hit per A** | **−0,0302 per A** |

Bootstrap a blocchi (blocco = giornata, coppie appaiate, 65 blocchi):
ΔBrier A−B = **−0,0302** (IC 95 % −0,0725 … +0,0108),
Δhit A−B = +0,0946 (IC 95 % −0,0667 … +0,2533).

Lettura onesta: il punto stimato favorisce **A**, l'intervallo include lo zero.
Con n = 74 non si dimostra che A è meglio; si dimostra che **non c'è nessuna
evidenza che B sia meglio**, che era la condizione posta per proporre il cambio.

Su tutte le 1 865 partite ammesse da entrambi: ΔBrier A−B = −0,0012
(IC 95 % −0,0029 … +0,0003), Δhit = +0,0038 (IC 95 % −0,0022 … +0,0099).

Per stagione il segno non è stabile: 2024/25 A hit 79,1 % / B 58,1 %
(n = 43); 2025/26 A 48,4 % / B 54,8 % (n = 31). Sotto-campioni da poche
decine di righe: non se ne ricava una direzione.

---

## 3. Il caso dell'esempio: A scarta l'intera partita, B la terrebbe

| | A scarta / B accetta | A accetta / B scarta |
|---|---:|---:|
| Aggregato | **155** (4,5 % delle candidate) | **0** |

Lo zero **non è un caso**: il mercato scelto da A viene valutato da B con la
stessa identica formula, quindi se passa i filtri per A passa anche per B.
B domina A per costruzione sull'ammissibilità (verificato anche da un test
proprietà su 500 casi casuali in `test_topmix_selector_replay.py`) e la
confidence di B è sempre ≥ quella di A.

Perché A aveva buttato via la partita:

- disaccordo Elo ≥ 0,25 sul solo mercato argmax: **94**
- confidence sotto soglia: **50**
- entrambi: **11**

Con quale mercato B la recupera: O2.5 **85**, 1 **39**, GG **18**, 2 **8**,
U2.5 **4**, NG **1**. Il pattern è chiaro: quasi sempre B ripiega su Over 2.5,
che non ha vincolo Elo (per costruzione `disagree = 0`) e quindi supera i filtri
molto più facilmente.

**Il punto che ribalta l'intuizione dell'esempio.** Su quelle stesse 155
partite, il mercato che A aveva scartato avrebbe avuto Brier **0,2216**
(hit 60,0 %, prob media 62,6 %); il mercato con cui B le recupera ha Brier
**0,2380** (hit 60,6 %, prob media 62,7 %). Le righe "salvate" da B non sono
righe migliori: sono righe **in più**, di qualità leggermente peggiore della
media di A (0,2312). Il mercato scartato non era, in media, "il migliore".

Esempi concreti (tabella completa in `results/topmix_selector_replay.md` §3):
Bayern–M'gladbach 33ª 2024/25, A: `1` all'84,9 % scartato per disaccordo Elo
0,265 → B mostra Over 2.5 al 78,6 %, finita 2-0 (B sbaglia, A aveva ragione ma
non poteva mostrarlo).

---

## 4. Copertura

| | A | B |
|---|---:|---:|
| Partite ammesse / candidate | 1 865 / 3 422 = **54,5 %** | 2 020 / 3 422 = **59,0 %** |
| Righe per giornata (362 giornate) | **5,15** | **5,58** |
| Giornate con 0 righe | 0 | 0 |

Per lega (A → B righe/giornata): Bundesliga 6,16 → 6,75; Premier 5,63 → 6,31;
La Liga 5,07 → 5,31; Serie A 4,78 → 4,97; Ligue 1 4,13 → 4,59.

**Ma la copertura in più non arriva al prodotto.** Il Top Mix mostra 10 righe:
nel replay il pool globale (5 leghe, settimana ISO del cutoff, 74 pool) riempie
**10 slot su 10 in tutti i pool sia con A sia con B**. Le 155 righe recuperate
da B non entrano quasi mai in top 10, perché la loro confidence è bassa
(62,7 % di media contro il 73,2 % della soglia effettiva della top 10).

Top 10 effettiva:

| | righe | slot medi | prob media | hit rate | Brier |
|---|---:|---:|---:|---:|---:|
| A | 740 | 10,00 | 73,2 % | 71,8 % | 0,2013 |
| B | 740 | 10,00 | 73,4 % | 72,0 % | 0,2010 |

Bootstrap a blocchi sul pool (74 weekend, delta non appaiato):
ΔBrier A−B = +0,0004 (IC 95 % −0,0041 … +0,0048),
Δhit A−B = −0,0027 (IC 95 % −0,0149 … +0,0095).
**Sul prodotto reale i due selettori sono indistinguibili.**

---

## 5. La calibrazione: l'ordine non è il colpevole

Baseline dei sette mercati sulle stesse 3 422 partite candidate, prima di
qualsiasi selettore (probabilità Poisson di produzione):

| Mercato | prob media | frequenza reale | gap | Brier |
|---|---:|---:|---:|---:|
| 1 | 43,7 % | 43,0 % | +0,007 | 0,2190 |
| X | 22,1 % | 25,2 % | −0,031 | 0,1880 |
| 2 | 34,2 % | 31,8 % | +0,024 | 0,1955 |
| O2.5 | 53,0 % | 53,3 % | −0,003 | 0,2448 |
| U2.5 | 47,0 % | 46,7 % | +0,003 | 0,2448 |
| GG | 53,9 % | 54,6 % | −0,006 | 0,2476 |
| NG | 46,1 % | 45,4 % | +0,006 | 0,2476 |

La baseline è **calibrata** (gap ≤ 3,1 pp). Sull'evento selezionato il gap sale
a +4,4 pp per A e +4,7 pp per B, con curve di affidabilità praticamente
sovrapposte (§7 del file dei risultati: bucket 0,60–0,65 → 56,0 % per A,
56,1 % per B). È l'effetto di coda del selezionare il massimo, e **colpisce A e
B nello stesso modo**: non è attribuibile all'ordine. Invertire l'ordine non
corregge nulla di questa sovrastima.

---

## 6. Perché B non vince (meccanica, non opinione)

`confidence` non è confrontabile fra mercati: sui 1X2 è una miscela
`0.6·Poisson + 0.4·Elo`, su O/U e GG/NG è Poisson puro con soglia più alta e
disaccordo Elo nullo **per costruzione**. Prendere il massimo su scale diverse
(B) non seleziona "il mercato più probabile": seleziona sistematicamente il
mercato che non ha il vincolo Elo. Si vede nella composizione: Over 2.5 passa da
132 righe (A) a 255 (B), +93 %, mentre 1/2/GG restano quasi invariati; in top 10
O2.5 passa da 72 a 111.

Rendere B davvero equo richiederebbe di rendere comparabili le due scale, cioè
toccare pesi e soglie — esattamente ciò che questo giro doveva **non** fare.

---

## 7. Conclusione operativa

1. **Nessun commit che cambia il selettore.** La condizione posta era «se il
   confronto è positivo per B». Non lo è: B non è meglio dove disaccorda
   (punto stimato a favore di A, IC che include zero), è identico sul prodotto
   (top 10), e la copertura in più che porta è di qualità inferiore e non
   raggiunge le 10 righe mostrate.
2. **Il difetto strutturale segnalato è reale e resta**: 155 partite su 3 422
   (4,5 %) vengono buttate via intere perché il *primo* mercato scelto non
   supera i filtri, 94 volte per il solo disaccordo Elo. Non è però vero, su
   questi dati, che il mercato scartato fosse quello migliore.
3. **Il prossimo passo utile non è cambiare l'ordine**: è il tracciamento
   (schema §5 del rapporto di audit) e la conferma prospettica 2026/27, perché
   su 2024/25–2025/26 qualunque scelta è già validation riusata.
4. Se in futuro si vuole riaprire B, va riaperto **insieme** al problema della
   comparabilità delle scale, con un protocollo che dichiara in anticipo il
   test set: cioè non su queste due stagioni.

---

## 8. Cosa questo lavoro NON ha fatto

- Nessuna modifica a formule, soglie (0.55 / 0.60 / 0.25), pesi (0.6/0.4),
  dedup, registro o JSONBin: `git status` mostra solo file nuovi in `audit/`.
- Nessuna chiamata a `save_prediction_entry`, `save_predictions`,
  `load_predictions`, `fetch_and_calc_top_mix`, `analisi_rapida_giornata`
  (verificato anche da test).
- Nessuna scrittura nel database di produzione: il point-in-time vive in una
  tmpdir e i percorsi vengono ripristinati (test dedicato).
- Nessun `--apply`, nessun merge, nessuna PR verso `main`. Il lavoro sta sul
  branch arena.
- Nessun uso di 2026/27 per tarare o validare.

## 9. Limiti dichiarati (protocollo §6, non aggirati)

Nessuno snapshot dello stato TIMED/SCHEDULED dell'API (i candidati sono
ricostruiti dai CSV); `matchday` ricostruito come n-esima partita di ciascuna
squadra (i recuperi differiscono dalla numerazione ufficiale); nomi dei CSV al
posto degli `shortName` dell'API; `MARKET_VALUES` statico applicato a stagioni
passate (leakage già dichiarato); xG di Understat rivisti dopo la partita;
orari dei CSV trattati come UTC; forma a 5 calcolata sul df multi-stagione come
in produzione; pool della top 10 = settimana ISO del cutoff; Elo ricalcolato,
non un dump. **Tutti questi limiti valgono identici per A e per B**, quindi non
spostano il confronto fra i due ordini — ma impediscono di chiamare questo
replay una riproduzione bit-identica del Top Mix live.

---

## 10. Riproduzione

```bash
python -m pip install -r SoccerMath/requirements.txt pytest
python audit/topmix_selector_replay.py --out audit/results   # ~2 min
python -m pytest audit SoccerMath -q --ignore=SoccerMath/test_theme_toggle.py
python SoccerMath/test_theme_toggle.py
```

Test eseguiti su questo branch: **361 passati, 1 010 subtest passati**
(più `test_theme_toggle.py`, che è uno script e non un modulo pytest).
Nota: `audit/test_reconstruct_topmix_match.py::TestHistoricalGitRef` richiede
la storia git completa (`git fetch --unshallow`): su un clone shallow fallisce
per assenza del commit `0695e9e`, non per il codice.
