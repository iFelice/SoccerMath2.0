# Overdispersion condizionale dei gol: Poisson vs Negative Binomial NB2 (audit sola lettura)

*Generato: 2026-09-13T23:29:08+00:00 — script `audit/diagnose_overdispersion_condizionale.py`, nessuna modifica a SoccerMath/.*

## Domanda e protocollo

Per ogni partita il motore a Due Teste assegna un lambda_home e un lambda_away **specifici per quella partita e diversi tra le due teste** (1X2: NORM-SUM xG+forma+mercato di `diagnose_elo_ensemble`; Totali: lambda puri modello B di `diagnose_form_totali`). Su quel lambda per-partita il motore assume distribuzioni Poisson indipendenti. Qui si tiene fisso il lambda e si chiede se i gol REALI siano piu' dispersi: in tal caso serve una NegBin NB2 con media lambda e varianza lambda + alpha*lambda^2 (alpha=0 e' esattamente il Poisson attuale).

- TRAIN 2022/23+2023/24: le prime 60 partite/lega restano nello stato ma sono escluse dal campione (cold start); **sul train si stima SOLAMENTE alpha** (MLE), in versione POOLED (un alpha su 5 leghe) e PER-LEGA (5 alpha), e separatamente per le due teste.
- VALIDATION 2024/25: conferma, nessuna stima/riottimizzazione.
- TEST 2025/26: sola lettura.
- IC bootstrap a 2000 resample (seed 20260905, come in `topmix_margins`/`diagnose_combo_1x2_totali`); una differenza dentro l'IC e' rumore.
- Le NegBin restano INDIPENDENTI tra casa e trasferta: cambia solo la pmf marginale (spessore delle code), non l'assunzione di indipendenza (quella e' oggetto dell'audit Dixon-Coles/combo). Griglia 15x15 troncata e non rinormalizzata, identica convenzione di produzione.
- Per il mercato 1X2 si usano i lambda della testa 1X2 (e alpha_1X2); per O/U2.5 e GG/NG i lambda della testa Totali (e alpha_TOT). Il riferimento 1X2 e' il Poisson puro della testa, non il blend con Elo: qui si testa l'assunzione di conteggio Poisson, non l'ensemble Elo.

## Conformita' del protocollo (verificata, non dichiarata)

Pmf NB2 custom vs `scipy.stats.nbinom`: max scarto 3.2e-14. Le marginali POISSON di questo audit sono state ricalcolate riga per riga e confrontate con gli audit di riferimento (stessi lambda, stessa costruzione della griglia):

| Lega | n righe | max\|scarto\| P(1) | P(X) | P(2) vs elo_ensemble | max\|scarto\| P(Over) | P(GG) vs form_totali B | esiti identici |
|---|---:|---:|---:|---:|---:|---:|---|
| Serie A | 760 | 0.0e+00 | 0.0e+00 | 0.0e+00 | 0.0e+00 | 0.0e+00 | si |
| Premier League | 760 | 0.0e+00 | 0.0e+00 | 0.0e+00 | 0.0e+00 | 0.0e+00 | si |
| La Liga | 760 | 0.0e+00 | 0.0e+00 | 0.0e+00 | 0.0e+00 | 0.0e+00 | si |
| Bundesliga | 612 | 0.0e+00 | 0.0e+00 | 0.0e+00 | 0.0e+00 | 0.0e+00 | si |
| Ligue 1 | 612 | 0.0e+00 | 0.0e+00 | 0.0e+00 | 0.0e+00 | 0.0e+00 | si |

Scarto atteso **0.0e+00** su tutte le colonne: questa analisi NON introduce un terzo modello, riusa esattamente il walk-forward di `diagnose_combo_1x2_totali.run_combo_model` (gia' allineato alle due diagnosi) e si limita a sostituire la pmf marginale. `check_state_invariance` verifica inoltre che emettere anche i treni non sposti di un bit le predizioni di validation/test.

## Copertura campioni

| Lega | Train (partite) | esclusi cold-start | Validation | Test | righe-squadra train |
|---|---:|---:|---:|---:|---:|
| Serie A | 700 | 60 | 380 | 380 | 1400 |
| Premier League | 700 | 60 | 380 | 380 | 1400 |
| La Liga | 700 | 60 | 380 | 380 | 1400 |
| Bundesliga | 552 | 60 | 306 | 306 | 1104 |
| Ligue 1 | 626 | 60 | 306 | 306 | 1252 |
| **AGGREGATO** | 3278 | 300 | 1752 | 1752 | 6556 |

## 1. STIMA di alpha (solo TRAIN): NB2 MLE condizionata al lambda per-partita

La stima NON usa la media gol di lega: ogni riga e' una prestazione squadra in una partita (gol osservati, lambda che il motore le aveva assegnato prima della partita). Alpha e' ricavato per massima verosimiglianza sulla NB2; il confronto e' lo stesso schema pooled vs per-lega gia' usato per il rho Dixon-Coles, qui ripetuto per le due teste perche' i lambda differiscono.

### Alpha dalla testa 1X2 (NORM-SUM xG+forma+mercato)

| Ambito | alpha MLE | IC 95% bootstrap | % resample al confine alpha=0 | n righe-squadra |
|---|---:|---|---:|---:|
| **POOLED 5 leghe** | 0.21904 | [0.18843; 0.25193] | 0.0% | 6556 |
| Bundesliga | 0.29767 | [0.22035; 0.38410] | 0.0% | 1104 |
| La Liga | 0.21075 | [0.14132; 0.29094] | 0.0% | 1400 |
| Ligue 1 | 0.14776 | [0.07927; 0.22420] | 0.0% | 1252 |
| Premier League | 0.20622 | [0.14504; 0.27173] | 0.0% | 1400 |
| Serie A | 0.21891 | [0.15071; 0.29393] | 0.0% | 1400 |

Dispersione condizionata descrittiva (stesso campione): la varianza attesa dal Poisson e' la media del lambda per-partita; il rapporto Var_reale/Var_Poisson e la statistica di Pearson sum((k-lambda)^2/lambda)/(n-1) sono >1 sotto overdispersion. La Pearson grezza e' pero' dominata dalle poche righe a lambda quasi zero (clip floor exp(-6), fallimenti del modello su squadre mal osservate: viaggiando a 1/lambda una singola riga lambda=0.025 con un gol vale ~40): si riporta anche la Pearson robusta sulle sole righe lambda>=0.1.

| Ambito | media lambda | media gol | Var reale | Var Poisson | rapporto | Pearson | Pearson (lambda>=0.1) | righe lambda<0.1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Bundesliga | 1.7713 | 1.6168 | 1.8703 | 1.7713 | 1.0559 | 2.1283 | 2.1283 | 0 |
| La Liga | 1.3193 | 1.2864 | 1.3882 | 1.3193 | 1.0522 | 5.4047 | 1.6667 | 3 |
| Ligue 1 | 1.3010 | 1.3538 | 1.3959 | 1.3010 | 1.0729 | 1.5954 | 1.5978 | 2 |
| Premier League | 1.5699 | 1.5393 | 1.7540 | 1.5699 | 1.1173 | 2.6437 | 1.7170 | 6 |
| Serie A | 1.3135 | 1.2993 | 1.3421 | 1.3135 | 1.0218 | 2.7860 | 1.9921 | 47 |
| POOLED | 1.4442 | 1.4117 | 1.5554 | 1.4442 | 1.0770 | 2.9749 | 1.8093 | 58 |

Robustezza di alpha: MLE escludendo le righe con lambda<0.1 (stima di sensibilita', non quella ufficiale): pooled 0.21476; per-lega Bundesliga 0.2977, La Liga 0.2068, Ligue 1 0.1477, Premier League 0.2041, Serie A 0.2034. L'alpha non si muove materialmente: l'overdispersion non e' un artefatto delle code di lambda.

### Alpha dalla testa Totali (modello B, lambda puri)

| Ambito | alpha MLE | IC 95% bootstrap | % resample al confine alpha=0 | n righe-squadra |
|---|---:|---|---:|---:|
| **POOLED 5 leghe** | 0.18911 | [0.15567; 0.22190] | 0.0% | 6556 |
| Bundesliga | 0.25376 | [0.17392; 0.33648] | 0.0% | 1104 |
| La Liga | 0.14345 | [0.08027; 0.21100] | 0.0% | 1400 |
| Ligue 1 | 0.16203 | [0.09293; 0.23549] | 0.0% | 1252 |
| Premier League | 0.18951 | [0.12411; 0.26240] | 0.0% | 1400 |
| Serie A | 0.18646 | [0.11325; 0.25956] | 0.0% | 1400 |

Dispersione condizionata descrittiva (stesso campione): la varianza attesa dal Poisson e' la media del lambda per-partita; il rapporto Var_reale/Var_Poisson e la statistica di Pearson sum((k-lambda)^2/lambda)/(n-1) sono >1 sotto overdispersion. La Pearson grezza e' pero' dominata dalle poche righe a lambda quasi zero (clip floor exp(-6), fallimenti del modello su squadre mal osservate: viaggiando a 1/lambda una singola riga lambda=0.025 con un gol vale ~40): si riporta anche la Pearson robusta sulle sole righe lambda>=0.1.

| Ambito | media lambda | media gol | Var reale | Var Poisson | rapporto | Pearson | Pearson (lambda>=0.1) | righe lambda<0.1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Bundesliga | 1.7568 | 1.6168 | 1.8703 | 1.7568 | 1.0646 | 1.8855 | 1.8855 | 0 |
| La Liga | 1.2974 | 1.2864 | 1.3882 | 1.2974 | 1.0700 | 5.1503 | 1.4117 | 3 |
| Ligue 1 | 1.3416 | 1.3538 | 1.3959 | 1.3416 | 1.0404 | 1.4184 | 1.4184 | 0 |
| Premier League | 1.5307 | 1.5393 | 1.7540 | 1.5307 | 1.1459 | 2.5008 | 1.6435 | 3 |
| Serie A | 1.3019 | 1.2993 | 1.3421 | 1.3019 | 1.0309 | 2.2662 | 2.0037 | 10 |
| POOLED | 1.4340 | 1.4117 | 1.5554 | 1.4340 | 1.0847 | 2.7046 | 1.6673 | 16 |

Robustezza di alpha: MLE escludendo le righe con lambda<0.1 (stima di sensibilita', non quella ufficiale): pooled 0.18739; per-lega Bundesliga 0.2538, La Liga 0.1396, Ligue 1 0.1620, Premier League 0.1895, Serie A 0.1817. L'alpha non si muove materialmente: l'overdispersion non e' un artefatto delle code di lambda.

### Diagnostica di forma e stabilita' (sola lettura)

Tre controlli che non entrano in nessuna probabilita' (le versioni NB usano sempre e solo gli alpha di TRAIN): (i) **alpha MLE calcolato anche su validation e test**: se resta dello stesso ordine di grandezza la sovra-dispersione non e' un accidente del train; (ii) **alpha method-of-moments** E[(k-lambda)^2-lambda]/E[lambda^2], che forza il secondo momento: se e' sistematicamente sotto l'MLE, l'MLE compra coda oltre che varianza; (iii) **frazione di zeri reale vs attesa**, che dice se la sovra-dispersione e' simmetrica (piu' zeri E piu' code, come vuole la NB2) o asimmetrica.

| Testa | Split (sola lettura) | alpha MLE | alpha MoM | P(0) reale | P(0) Poisson E[e^-lam] | P(0) a media costante e^-E[lam] | P(0) NB (alpha train) | E[(k-lam)^2] reale | Poisson E[lam] | NB E[lam+alpha*lam^2] |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1x2 | train | 0.2190 | 0.1680 | 0.258 | 0.338 | 0.236 | 0.375 | 1.983 | 1.444 | 2.146 |
| 1x2 | validation | 0.2017 | 0.1630 | 0.253 | 0.339 | 0.242 | 0.376 | 1.913 | 1.420 | 2.083 |
| 1x2 | test | 0.1785 | 0.1378 | 0.263 | 0.347 | 0.250 | 0.384 | 1.785 | 1.388 | 2.019 |
| tot | train | 0.1891 | 0.1455 | 0.258 | 0.314 | 0.238 | 0.348 | 1.846 | 1.434 | 1.969 |
| tot | validation | 0.1885 | 0.1498 | 0.253 | 0.314 | 0.241 | 0.349 | 1.831 | 1.421 | 1.939 |
| tot | test | 0.1310 | 0.1005 | 0.263 | 0.323 | 0.250 | 0.357 | 1.649 | 1.388 | 1.879 |

Lettura: gli alpha di validation e test restano grandi (0.13-0.20), confermando la direzione del train; ma la forma reale e' ASIMMETRICA: la frazione di zero gol osservata (0.25-0.26) e' **inferiore** a quella attesa dal Poisson di questi lambda (testa 1X2 0.34, testa Totali 0.31 sul train), mentre l'NB2 per costruzione aggiunge massa sugli zeri portandola ancora piu' su (0.37/0.35). Il modello di conteggio ha code alte piu' spesse del Poisson ma NON piu' zeri: e' questo il motivo strutturale per cui la NB2 migliora i mercati di soglia (1X2, Over) e peggiora GG/NG, che dagli zeri dipende direttamente. Il confronto con e^-E[lambda] (0.24/0.24, la P(0) di un Poisson a media costante) mostra inoltre che i lambda dell'audit sono TROPPO SPARPAGLIATI (Var lambda 0.77 sulla testa Totali): l'eccesso di zeri attesi viene dallo spread dei lambda, non dai gol. L'alpha MLE risponde dunque correttamente alla domanda 'dato QUESTO lambda per-partita, il Poisson sottovaluta la dispersione condizionata?' (si': E[(k-lambda)^2] vale 1.8-2.0 contro E[lambda] 1.4), ma ingloba coda reale E misspecificazione dei lambda: non e' la prova che i gol seguano una NB2 in natura. Questa diagnostica non ritara nulla: le probabilita' usano sempre e solo l'alpha di train.

## 2. VALUTAZIONE fuori campione: Brier e LogLoss delle 3 versioni

Per ogni mercato: POISSON (attuale), NB-pooled e NB-per-lega, su validation e test. Delta = NegBin - Poisson (negativo = migliora); IC 95% bootstrap sulla differenza appaiata riga per riga.

### Mercato 1X2 (testa 1X2, alpha_1X2)

**Brier**

| Lega | Split | POISSON | NB-pooled | NB-per-lega | Δ pooled (IC 95%) | verdetto | Δ per-lega (IC 95%) | verdetto |
|---|---|---:|---:|---:|---:|---|---:|---|
| AGGREGATO | validation | 0.6522 | 0.6362 | 0.6362 | -0.0160 [-0.0189; -0.0131] | MIGLIORE (IC senza zero) | -0.0160 [-0.0188; -0.0131] | MIGLIORE (IC senza zero) |
| AGGREGATO | test | 0.6471 | 0.6324 | 0.6324 | -0.0147 [-0.0176; -0.0119] | MIGLIORE (IC senza zero) | -0.0147 [-0.0176; -0.0120] | MIGLIORE (IC senza zero) |
| Serie A | validation | 0.6740 | 0.6544 | 0.6544 | -0.0197 [-0.0258; -0.0139] | MIGLIORE (IC senza zero) | -0.0196 [-0.0257; -0.0140] | MIGLIORE (IC senza zero) |
| Serie A | test | 0.6322 | 0.6187 | 0.6187 | -0.0135 [-0.0197; -0.0076] | MIGLIORE (IC senza zero) | -0.0135 [-0.0191; -0.0077] | MIGLIORE (IC senza zero) |
| Premier League | validation | 0.6428 | 0.6277 | 0.6284 | -0.0151 [-0.0213; -0.0085] | MIGLIORE (IC senza zero) | -0.0144 [-0.0205; -0.0085] | MIGLIORE (IC senza zero) |
| Premier League | test | 0.6577 | 0.6419 | 0.6427 | -0.0157 [-0.0214; -0.0098] | MIGLIORE (IC senza zero) | -0.0150 [-0.0203; -0.0095] | MIGLIORE (IC senza zero) |
| La Liga | validation | 0.6237 | 0.6129 | 0.6132 | -0.0108 [-0.0162; -0.0057] | MIGLIORE (IC senza zero) | -0.0105 [-0.0157; -0.0055] | MIGLIORE (IC senza zero) |
| La Liga | test | 0.6350 | 0.6246 | 0.6249 | -0.0103 [-0.0157; -0.0054] | MIGLIORE (IC senza zero) | -0.0100 [-0.0149; -0.0051] | MIGLIORE (IC senza zero) |
| Bundesliga | validation | 0.6663 | 0.6469 | 0.6418 | -0.0193 [-0.0276; -0.0118] | MIGLIORE (IC senza zero) | -0.0245 [-0.0346; -0.0150] | MIGLIORE (IC senza zero) |
| Bundesliga | test | 0.6631 | 0.6430 | 0.6377 | -0.0202 [-0.0279; -0.0124] | MIGLIORE (IC senza zero) | -0.0254 [-0.0358; -0.0156] | MIGLIORE (IC senza zero) |
| Ligue 1 | validation | 0.6580 | 0.6422 | 0.6464 | -0.0158 [-0.0225; -0.0094] | MIGLIORE (IC senza zero) | -0.0116 [-0.0166; -0.0070] | MIGLIORE (IC senza zero) |
| Ligue 1 | test | 0.6513 | 0.6364 | 0.6404 | -0.0149 [-0.0220; -0.0084] | MIGLIORE (IC senza zero) | -0.0109 [-0.0154; -0.0064] | MIGLIORE (IC senza zero) |

**LogLoss**

| Lega | Split | POISSON | NB-pooled | NB-per-lega | Δ pooled (IC 95%) | verdetto | Δ per-lega (IC 95%) | verdetto |
|---|---|---:|---:|---:|---:|---|---:|---|
| AGGREGATO | validation | 1.1345 | 1.0871 | 1.0868 | -0.0474 [-0.0574; -0.0381] | MIGLIORE (IC senza zero) | -0.0477 [-0.0587; -0.0376] | MIGLIORE (IC senza zero) |
| AGGREGATO | test | 1.1154 | 1.0760 | 1.0758 | -0.0394 [-0.0468; -0.0315] | MIGLIORE (IC senza zero) | -0.0397 [-0.0480; -0.0317] | MIGLIORE (IC senza zero) |
| Serie A | validation | 1.1556 | 1.1093 | 1.1093 | -0.0464 [-0.0620; -0.0306] | MIGLIORE (IC senza zero) | -0.0463 [-0.0628; -0.0314] | MIGLIORE (IC senza zero) |
| Serie A | test | 1.1208 | 1.0769 | 1.0769 | -0.0439 [-0.0643; -0.0271] | MIGLIORE (IC senza zero) | -0.0438 [-0.0623; -0.0256] | MIGLIORE (IC senza zero) |
| Premier League | validation | 1.0910 | 1.0550 | 1.0564 | -0.0360 [-0.0519; -0.0215] | MIGLIORE (IC senza zero) | -0.0346 [-0.0499; -0.0198] | MIGLIORE (IC senza zero) |
| Premier League | test | 1.1033 | 1.0723 | 1.0735 | -0.0310 [-0.0452; -0.0182] | MIGLIORE (IC senza zero) | -0.0298 [-0.0428; -0.0173] | MIGLIORE (IC senza zero) |
| La Liga | validation | 1.0777 | 1.0389 | 1.0398 | -0.0388 [-0.0610; -0.0202] | MIGLIORE (IC senza zero) | -0.0379 [-0.0601; -0.0198] | MIGLIORE (IC senza zero) |
| La Liga | test | 1.1019 | 1.0726 | 1.0733 | -0.0293 [-0.0446; -0.0152] | MIGLIORE (IC senza zero) | -0.0287 [-0.0429; -0.0149] | MIGLIORE (IC senza zero) |
| Bundesliga | validation | 1.2347 | 1.1562 | 1.1416 | -0.0785 [-0.1175; -0.0444] | MIGLIORE (IC senza zero) | -0.0931 [-0.1410; -0.0542] | MIGLIORE (IC senza zero) |
| Bundesliga | test | 1.1603 | 1.0984 | 1.0864 | -0.0619 [-0.0882; -0.0362] | MIGLIORE (IC senza zero) | -0.0739 [-0.1054; -0.0456] | MIGLIORE (IC senza zero) |
| Ligue 1 | validation | 1.1326 | 1.0900 | 1.1000 | -0.0426 [-0.0612; -0.0256] | MIGLIORE (IC senza zero) | -0.0327 [-0.0469; -0.0197] | MIGLIORE (IC senza zero) |
| Ligue 1 | test | 1.0957 | 1.0614 | 1.0696 | -0.0343 [-0.0511; -0.0197] | MIGLIORE (IC senza zero) | -0.0262 [-0.0380; -0.0152] | MIGLIORE (IC senza zero) |


### Mercato O/U2.5 (testa Totali, alpha_TOT)

**Brier**

| Lega | Split | POISSON | NB-pooled | NB-per-lega | Δ pooled (IC 95%) | verdetto | Δ per-lega (IC 95%) | verdetto |
|---|---|---:|---:|---:|---:|---|---:|---|
| AGGREGATO | validation | 0.2744 | 0.2694 | 0.2694 | -0.0050 [-0.0066; -0.0034] | MIGLIORE (IC senza zero) | -0.0050 [-0.0067; -0.0034] | MIGLIORE (IC senza zero) |
| AGGREGATO | test | 0.2701 | 0.2661 | 0.2662 | -0.0040 [-0.0057; -0.0025] | MIGLIORE (IC senza zero) | -0.0039 [-0.0055; -0.0023] | MIGLIORE (IC senza zero) |
| Serie A | validation | 0.2896 | 0.2830 | 0.2831 | -0.0066 [-0.0100; -0.0035] | MIGLIORE (IC senza zero) | -0.0066 [-0.0097; -0.0033] | MIGLIORE (IC senza zero) |
| Serie A | test | 0.2900 | 0.2830 | 0.2831 | -0.0070 [-0.0104; -0.0038] | MIGLIORE (IC senza zero) | -0.0069 [-0.0101; -0.0039] | MIGLIORE (IC senza zero) |
| Premier League | validation | 0.2634 | 0.2579 | 0.2579 | -0.0055 [-0.0094; -0.0017] | MIGLIORE (IC senza zero) | -0.0055 [-0.0094; -0.0015] | MIGLIORE (IC senza zero) |
| Premier League | test | 0.2659 | 0.2607 | 0.2607 | -0.0052 [-0.0086; -0.0017] | MIGLIORE (IC senza zero) | -0.0052 [-0.0088; -0.0014] | MIGLIORE (IC senza zero) |
| La Liga | validation | 0.2572 | 0.2547 | 0.2551 | -0.0025 [-0.0056; 0.0004] | entro l'IC: rumore | -0.0021 [-0.0047; 0.0002] | entro l'IC: rumore |
| La Liga | test | 0.2538 | 0.2522 | 0.2523 | -0.0017 [-0.0045; 0.0012] | entro l'IC: rumore | -0.0015 [-0.0037; 0.0008] | entro l'IC: rumore |
| Bundesliga | validation | 0.2738 | 0.2681 | 0.2672 | -0.0057 [-0.0107; -0.0008] | MIGLIORE (IC senza zero) | -0.0066 [-0.0131; -0.0007] | MIGLIORE (IC senza zero) |
| Bundesliga | test | 0.2686 | 0.2666 | 0.2666 | -0.0020 [-0.0062; 0.0024] | entro l'IC: rumore | -0.0020 [-0.0074; 0.0036] | entro l'IC: rumore |
| Ligue 1 | validation | 0.2912 | 0.2861 | 0.2866 | -0.0051 [-0.0084; -0.0015] | MIGLIORE (IC senza zero) | -0.0045 [-0.0078; -0.0016] | MIGLIORE (IC senza zero) |
| Ligue 1 | test | 0.2725 | 0.2684 | 0.2688 | -0.0040 [-0.0079; -0.0006] | MIGLIORE (IC senza zero) | -0.0037 [-0.0069; -0.0004] | MIGLIORE (IC senza zero) |

**LogLoss**

| Lega | Split | POISSON | NB-pooled | NB-per-lega | Δ pooled (IC 95%) | verdetto | Δ per-lega (IC 95%) | verdetto |
|---|---|---:|---:|---:|---:|---|---:|---|
| AGGREGATO | validation | 0.7564 | 0.7404 | 0.7402 | -0.0160 [-0.0207; -0.0111] | MIGLIORE (IC senza zero) | -0.0161 [-0.0211; -0.0110] | MIGLIORE (IC senza zero) |
| AGGREGATO | test | 0.7507 | 0.7368 | 0.7369 | -0.0140 [-0.0185; -0.0096] | MIGLIORE (IC senza zero) | -0.0138 [-0.0186; -0.0094] | MIGLIORE (IC senza zero) |
| Serie A | validation | 0.7911 | 0.7703 | 0.7704 | -0.0208 [-0.0313; -0.0114] | MIGLIORE (IC senza zero) | -0.0206 [-0.0319; -0.0110] | MIGLIORE (IC senza zero) |
| Serie A | test | 0.8166 | 0.7908 | 0.7911 | -0.0257 [-0.0370; -0.0156] | MIGLIORE (IC senza zero) | -0.0255 [-0.0364; -0.0154] | MIGLIORE (IC senza zero) |
| Premier League | validation | 0.7273 | 0.7117 | 0.7117 | -0.0156 [-0.0261; -0.0050] | MIGLIORE (IC senza zero) | -0.0157 [-0.0258; -0.0056] | MIGLIORE (IC senza zero) |
| Premier League | test | 0.7344 | 0.7188 | 0.7188 | -0.0156 [-0.0263; -0.0056] | MIGLIORE (IC senza zero) | -0.0156 [-0.0260; -0.0059] | MIGLIORE (IC senza zero) |
| La Liga | validation | 0.7162 | 0.7083 | 0.7093 | -0.0079 [-0.0171; 0.0001] | entro l'IC: rumore | -0.0068 [-0.0142; -0.0002] | MIGLIORE (IC senza zero) |
| La Liga | test | 0.7046 | 0.7010 | 0.7013 | -0.0036 [-0.0106; 0.0034] | entro l'IC: rumore | -0.0033 [-0.0089; 0.0021] | entro l'IC: rumore |
| Bundesliga | validation | 0.7705 | 0.7469 | 0.7432 | -0.0236 [-0.0392; -0.0091] | MIGLIORE (IC senza zero) | -0.0273 [-0.0469; -0.0092] | MIGLIORE (IC senza zero) |
| Bundesliga | test | 0.7491 | 0.7375 | 0.7365 | -0.0116 [-0.0260; 0.0013] | entro l'IC: rumore | -0.0126 [-0.0288; 0.0036] | entro l'IC: rumore |
| Ligue 1 | validation | 0.7851 | 0.7724 | 0.7737 | -0.0127 [-0.0210; -0.0044] | MIGLIORE (IC senza zero) | -0.0115 [-0.0193; -0.0042] | MIGLIORE (IC senza zero) |
| Ligue 1 | test | 0.7480 | 0.7356 | 0.7367 | -0.0124 [-0.0226; -0.0029] | MIGLIORE (IC senza zero) | -0.0113 [-0.0201; -0.0034] | MIGLIORE (IC senza zero) |


### Mercato GG/NG (testa Totali, alpha_TOT)

**Brier**

| Lega | Split | POISSON | NB-pooled | NB-per-lega | Δ pooled (IC 95%) | verdetto | Δ per-lega (IC 95%) | verdetto |
|---|---|---:|---:|---:|---:|---|---:|---|
| AGGREGATO | validation | 0.2788 | 0.2844 | 0.2841 | +0.0056 [0.0033; 0.0078] | PEGGIORE (IC senza zero) | +0.0053 [0.0029; 0.0076] | PEGGIORE (IC senza zero) |
| AGGREGATO | test | 0.2731 | 0.2788 | 0.2786 | +0.0057 [0.0035; 0.0079] | PEGGIORE (IC senza zero) | +0.0055 [0.0033; 0.0076] | PEGGIORE (IC senza zero) |
| Serie A | validation | 0.2987 | 0.3046 | 0.3045 | +0.0059 [0.0019; 0.0102] | PEGGIORE (IC senza zero) | +0.0058 [0.0017; 0.0098] | PEGGIORE (IC senza zero) |
| Serie A | test | 0.2845 | 0.2878 | 0.2878 | +0.0033 [-0.0005; 0.0070] | entro l'IC: rumore | +0.0032 [-0.0002; 0.0067] | entro l'IC: rumore |
| Premier League | validation | 0.2571 | 0.2600 | 0.2600 | +0.0028 [-0.0028; 0.0083] | entro l'IC: rumore | +0.0029 [-0.0027; 0.0084] | entro l'IC: rumore |
| Premier League | test | 0.2603 | 0.2624 | 0.2624 | +0.0022 [-0.0034; 0.0078] | entro l'IC: rumore | +0.0022 [-0.0038; 0.0079] | entro l'IC: rumore |
| La Liga | validation | 0.2785 | 0.2873 | 0.2850 | +0.0088 [0.0044; 0.0130] | PEGGIORE (IC senza zero) | +0.0065 [0.0032; 0.0097] | PEGGIORE (IC senza zero) |
| La Liga | test | 0.2683 | 0.2799 | 0.2769 | +0.0115 [0.0075; 0.0157] | PEGGIORE (IC senza zero) | +0.0086 [0.0053; 0.0119] | PEGGIORE (IC senza zero) |
| Bundesliga | validation | 0.2822 | 0.2866 | 0.2889 | +0.0043 [-0.0016; 0.0096] | entro l'IC: rumore | +0.0067 [-0.0005; 0.0140] | entro l'IC: rumore |
| Bundesliga | test | 0.2908 | 0.2989 | 0.3024 | +0.0082 [0.0023; 0.0136] | PEGGIORE (IC senza zero) | +0.0116 [0.0043; 0.0184] | PEGGIORE (IC senza zero) |
| Ligue 1 | validation | 0.2780 | 0.2839 | 0.2828 | +0.0059 [-0.0000; 0.0115] | entro l'IC: rumore | +0.0049 [-0.0003; 0.0099] | entro l'IC: rumore |
| Ligue 1 | test | 0.2629 | 0.2662 | 0.2655 | +0.0033 [-0.0022; 0.0086] | entro l'IC: rumore | +0.0026 [-0.0022; 0.0073] | entro l'IC: rumore |

**LogLoss**

| Lega | Split | POISSON | NB-pooled | NB-per-lega | Δ pooled (IC 95%) | verdetto | Δ per-lega (IC 95%) | verdetto |
|---|---|---:|---:|---:|---:|---|---:|---|
| AGGREGATO | validation | 0.7682 | 0.7813 | 0.7806 | +0.0131 [0.0076; 0.0181] | PEGGIORE (IC senza zero) | +0.0124 [0.0070; 0.0176] | PEGGIORE (IC senza zero) |
| AGGREGATO | test | 0.7596 | 0.7724 | 0.7721 | +0.0128 [0.0079; 0.0179] | PEGGIORE (IC senza zero) | +0.0125 [0.0073; 0.0173] | PEGGIORE (IC senza zero) |
| Serie A | validation | 0.8127 | 0.8289 | 0.8287 | +0.0162 [0.0074; 0.0249] | PEGGIORE (IC senza zero) | +0.0159 [0.0075; 0.0249] | PEGGIORE (IC senza zero) |
| Serie A | test | 0.8305 | 0.8417 | 0.8415 | +0.0112 [0.0033; 0.0189] | PEGGIORE (IC senza zero) | +0.0110 [0.0032; 0.0190] | PEGGIORE (IC senza zero) |
| Premier League | validation | 0.7114 | 0.7169 | 0.7169 | +0.0055 [-0.0074; 0.0183] | entro l'IC: rumore | +0.0055 [-0.0072; 0.0184] | entro l'IC: rumore |
| Premier League | test | 0.7192 | 0.7225 | 0.7225 | +0.0033 [-0.0093; 0.0164] | entro l'IC: rumore | +0.0033 [-0.0095; 0.0160] | entro l'IC: rumore |
| La Liga | validation | 0.7550 | 0.7752 | 0.7699 | +0.0202 [0.0114; 0.0290] | PEGGIORE (IC senza zero) | +0.0149 [0.0080; 0.0212] | PEGGIORE (IC senza zero) |
| La Liga | test | 0.7336 | 0.7588 | 0.7523 | +0.0252 [0.0161; 0.0342] | PEGGIORE (IC senza zero) | +0.0187 [0.0115; 0.0259] | PEGGIORE (IC senza zero) |
| Bundesliga | validation | 0.8166 | 0.8259 | 0.8314 | +0.0093 [-0.0044; 0.0217] | entro l'IC: rumore | +0.0148 [-0.0024; 0.0319] | entro l'IC: rumore |
| Bundesliga | test | 0.7921 | 0.8087 | 0.8166 | +0.0166 [0.0021; 0.0305] | PEGGIORE (IC senza zero) | +0.0246 [0.0077; 0.0410] | PEGGIORE (IC senza zero) |
| Ligue 1 | validation | 0.7515 | 0.7649 | 0.7624 | +0.0134 [0.0013; 0.0257] | PEGGIORE (IC senza zero) | +0.0110 [0.0007; 0.0212] | PEGGIORE (IC senza zero) |
| Ligue 1 | test | 0.7216 | 0.7291 | 0.7275 | +0.0075 [-0.0039; 0.0191] | entro l'IC: rumore | +0.0059 [-0.0042; 0.0163] | entro l'IC: rumore |


## 3. Affidabilita' per quintili (pred. media vs frequenza osservata)

Stessa lente dell'audit combo: quintili della previsione, con attenzione alle code Q1/Q5 (dove la sessione precedente aveva trovato il problema: ultimo quintile che prometteva 0.65 e realizzava 0.40). Per ogni mercato si mostra il POISSON e la versione NegBin migliore sul TRAIN (NB-pooled vs NB-per-lega scelta per Brier train: 1X2 -> NB-per-lega (alpha della lega), O/U2.5 -> NB-pooled (alpha unico 5 leghe), GG/NG -> NB-per-lega (alpha della lega)).

### 1X2

**esito 1 (casa) — VALIDATION (n=1752)**

| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |
|---|---|---:|---:|---:|---:|
| POISSON | **Q1** | 351 | 0.0712 | 0.2308 | -0.1596 |
| POISSON | Q2 | 350 | 0.2439 | 0.2886 | -0.0447 |
| POISSON | Q3 | 350 | 0.4183 | 0.4343 | -0.0160 |
| POISSON | Q4 | 350 | 0.6130 | 0.5143 | +0.0987 |
| POISSON | **Q5** | 351 | 0.8555 | 0.6325 | +0.2230 |
| NB-per-lega (alpha della lega) | **Q1** | 351 | 0.0906 | 0.2194 | -0.1288 |
| NB-per-lega (alpha della lega) | Q2 | 350 | 0.2589 | 0.2971 | -0.0382 |
| NB-per-lega (alpha della lega) | Q3 | 350 | 0.4134 | 0.4314 | -0.0180 |
| NB-per-lega (alpha della lega) | Q4 | 350 | 0.5817 | 0.5257 | +0.0560 |
| NB-per-lega (alpha della lega) | **Q5** | 351 | 0.7982 | 0.6268 | +0.1714 |

**esito 1 (casa) — TEST (n=1752)**

| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |
|---|---|---:|---:|---:|---:|
| POISSON | **Q1** | 351 | 0.0652 | 0.2165 | -0.1513 |
| POISSON | Q2 | 350 | 0.2271 | 0.3829 | -0.1557 |
| POISSON | Q3 | 350 | 0.4041 | 0.4286 | -0.0245 |
| POISSON | Q4 | 350 | 0.6089 | 0.5143 | +0.0946 |
| POISSON | **Q5** | 351 | 0.8527 | 0.6581 | +0.1945 |
| NB-per-lega (alpha della lega) | **Q1** | 351 | 0.0837 | 0.2194 | -0.1357 |
| NB-per-lega (alpha della lega) | Q2 | 350 | 0.2435 | 0.3914 | -0.1480 |
| NB-per-lega (alpha della lega) | Q3 | 350 | 0.4011 | 0.4171 | -0.0160 |
| NB-per-lega (alpha della lega) | Q4 | 350 | 0.5781 | 0.5114 | +0.0667 |
| NB-per-lega (alpha della lega) | **Q5** | 351 | 0.7961 | 0.6610 | +0.1351 |

**esito X (pareggio) — VALIDATION (n=1752)**

| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |
|---|---|---:|---:|---:|---:|
| POISSON | **Q1** | 351 | 0.0728 | 0.1937 | -0.1209 |
| POISSON | Q2 | 350 | 0.1659 | 0.2343 | -0.0684 |
| POISSON | Q3 | 350 | 0.2199 | 0.2629 | -0.0430 |
| POISSON | Q4 | 350 | 0.2635 | 0.2686 | -0.0051 |
| POISSON | **Q5** | 351 | 0.3370 | 0.2877 | +0.0492 |
| NB-per-lega (alpha della lega) | **Q1** | 351 | 0.1073 | 0.1880 | -0.0808 |
| NB-per-lega (alpha della lega) | Q2 | 350 | 0.1803 | 0.2514 | -0.0711 |
| NB-per-lega (alpha della lega) | Q3 | 350 | 0.2254 | 0.2486 | -0.0231 |
| NB-per-lega (alpha della lega) | Q4 | 350 | 0.2686 | 0.2714 | -0.0028 |
| NB-per-lega (alpha della lega) | **Q5** | 351 | 0.3443 | 0.2877 | +0.0566 |

**esito X (pareggio) — TEST (n=1752)**

| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |
|---|---|---:|---:|---:|---:|
| POISSON | **Q1** | 351 | 0.0754 | 0.1795 | -0.1040 |
| POISSON | Q2 | 350 | 0.1680 | 0.2629 | -0.0949 |
| POISSON | Q3 | 350 | 0.2223 | 0.2600 | -0.0377 |
| POISSON | Q4 | 350 | 0.2668 | 0.2800 | -0.0132 |
| POISSON | **Q5** | 351 | 0.3458 | 0.2906 | +0.0552 |
| NB-per-lega (alpha della lega) | **Q1** | 351 | 0.1095 | 0.2165 | -0.1071 |
| NB-per-lega (alpha della lega) | Q2 | 350 | 0.1840 | 0.2400 | -0.0560 |
| NB-per-lega (alpha della lega) | Q3 | 350 | 0.2293 | 0.2486 | -0.0193 |
| NB-per-lega (alpha della lega) | Q4 | 350 | 0.2714 | 0.2771 | -0.0057 |
| NB-per-lega (alpha della lega) | **Q5** | 351 | 0.3540 | 0.2906 | +0.0634 |

**esito 2 (trasferta) — VALIDATION (n=1752)**

| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |
|---|---|---:|---:|---:|---:|
| POISSON | **Q1** | 351 | 0.0385 | 0.1453 | -0.1068 |
| POISSON | Q2 | 350 | 0.1510 | 0.2400 | -0.0890 |
| POISSON | Q3 | 350 | 0.2954 | 0.3571 | -0.0617 |
| POISSON | Q4 | 350 | 0.4825 | 0.3943 | +0.0882 |
| POISSON | **Q5** | 351 | 0.7709 | 0.5157 | +0.2552 |
| NB-per-lega (alpha della lega) | **Q1** | 351 | 0.0562 | 0.1510 | -0.0948 |
| NB-per-lega (alpha della lega) | Q2 | 350 | 0.1727 | 0.2371 | -0.0644 |
| NB-per-lega (alpha della lega) | Q3 | 350 | 0.3062 | 0.3571 | -0.0509 |
| NB-per-lega (alpha della lega) | Q4 | 350 | 0.4691 | 0.3943 | +0.0748 |
| NB-per-lega (alpha della lega) | **Q5** | 351 | 0.7221 | 0.5128 | +0.2092 |

**esito 2 (trasferta) — TEST (n=1752)**

| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |
|---|---|---:|---:|---:|---:|
| POISSON | **Q1** | 351 | 0.0365 | 0.1368 | -0.1002 |
| POISSON | Q2 | 350 | 0.1512 | 0.2143 | -0.0631 |
| POISSON | Q3 | 350 | 0.3061 | 0.2829 | +0.0233 |
| POISSON | Q4 | 350 | 0.4965 | 0.3514 | +0.1450 |
| POISSON | **Q5** | 351 | 0.7729 | 0.5413 | +0.2316 |
| NB-per-lega (alpha della lega) | **Q1** | 351 | 0.0532 | 0.1481 | -0.0950 |
| NB-per-lega (alpha della lega) | Q2 | 350 | 0.1734 | 0.2000 | -0.0266 |
| NB-per-lega (alpha della lega) | Q3 | 350 | 0.3151 | 0.2914 | +0.0237 |
| NB-per-lega (alpha della lega) | Q4 | 350 | 0.4808 | 0.3543 | +0.1265 |
| NB-per-lega (alpha della lega) | **Q5** | 351 | 0.7233 | 0.5328 | +0.1906 |


### O/U2.5

**Over 2.5 — VALIDATION (n=1752)**

| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |
|---|---|---:|---:|---:|---:|
| POISSON | **Q1** | 351 | 0.2535 | 0.5043 | -0.2507 |
| POISSON | Q2 | 350 | 0.3905 | 0.5057 | -0.1153 |
| POISSON | Q3 | 350 | 0.5051 | 0.5314 | -0.0263 |
| POISSON | Q4 | 350 | 0.6296 | 0.5429 | +0.0868 |
| POISSON | **Q5** | 351 | 0.7876 | 0.5869 | +0.2007 |
| NB-pooled (alpha unico 5 leghe) | **Q1** | 351 | 0.2575 | 0.5043 | -0.2468 |
| NB-pooled (alpha unico 5 leghe) | Q2 | 350 | 0.3822 | 0.5114 | -0.1292 |
| NB-pooled (alpha unico 5 leghe) | Q3 | 350 | 0.4828 | 0.5286 | -0.0458 |
| NB-pooled (alpha unico 5 leghe) | Q4 | 350 | 0.5896 | 0.5429 | +0.0468 |
| NB-pooled (alpha unico 5 leghe) | **Q5** | 351 | 0.7286 | 0.5840 | +0.1445 |

**Over 2.5 — TEST (n=1752)**

| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |
|---|---|---:|---:|---:|---:|
| POISSON | **Q1** | 351 | 0.2347 | 0.4929 | -0.2582 |
| POISSON | Q2 | 350 | 0.3871 | 0.4771 | -0.0900 |
| POISSON | Q3 | 350 | 0.4947 | 0.5314 | -0.0368 |
| POISSON | Q4 | 350 | 0.6105 | 0.5400 | +0.0705 |
| POISSON | **Q5** | 351 | 0.7740 | 0.6097 | +0.1644 |
| NB-pooled (alpha unico 5 leghe) | **Q1** | 351 | 0.2393 | 0.4929 | -0.2536 |
| NB-pooled (alpha unico 5 leghe) | Q2 | 350 | 0.3791 | 0.4800 | -0.1009 |
| NB-pooled (alpha unico 5 leghe) | Q3 | 350 | 0.4736 | 0.5314 | -0.0579 |
| NB-pooled (alpha unico 5 leghe) | Q4 | 350 | 0.5731 | 0.5371 | +0.0360 |
| NB-pooled (alpha unico 5 leghe) | **Q5** | 351 | 0.7166 | 0.6097 | +0.1069 |


### GG/NG

**GG — VALIDATION (n=1752)**

| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |
|---|---|---:|---:|---:|---:|
| POISSON | **Q1** | 351 | 0.2323 | 0.5442 | -0.3119 |
| POISSON | Q2 | 350 | 0.3691 | 0.5771 | -0.2081 |
| POISSON | Q3 | 350 | 0.4485 | 0.5486 | -0.1001 |
| POISSON | Q4 | 350 | 0.5387 | 0.5200 | +0.0187 |
| POISSON | **Q5** | 351 | 0.6793 | 0.5726 | +0.1067 |
| NB-per-lega (alpha della lega) | **Q1** | 351 | 0.2138 | 0.5470 | -0.3332 |
| NB-per-lega (alpha della lega) | Q2 | 350 | 0.3372 | 0.5771 | -0.2399 |
| NB-per-lega (alpha della lega) | Q3 | 350 | 0.4076 | 0.5486 | -0.1410 |
| NB-per-lega (alpha della lega) | Q4 | 350 | 0.4857 | 0.5200 | -0.0343 |
| NB-per-lega (alpha della lega) | **Q5** | 351 | 0.6065 | 0.5698 | +0.0367 |

**GG — TEST (n=1752)**

| Versione | Bin | n | Pred. media | Frequ. osservata | Bias |
|---|---|---:|---:|---:|---:|
| POISSON | **Q1** | 351 | 0.2122 | 0.4758 | -0.2636 |
| POISSON | Q2 | 350 | 0.3609 | 0.5514 | -0.1905 |
| POISSON | Q3 | 350 | 0.4414 | 0.5029 | -0.0615 |
| POISSON | Q4 | 350 | 0.5270 | 0.5943 | -0.0673 |
| POISSON | **Q5** | 351 | 0.6718 | 0.5698 | +0.1020 |
| NB-per-lega (alpha della lega) | **Q1** | 351 | 0.1955 | 0.4786 | -0.2831 |
| NB-per-lega (alpha della lega) | Q2 | 350 | 0.3294 | 0.5486 | -0.2192 |
| NB-per-lega (alpha della lega) | Q3 | 350 | 0.4012 | 0.5000 | -0.0988 |
| NB-per-lega (alpha della lega) | Q4 | 350 | 0.4750 | 0.5971 | -0.1222 |
| NB-per-lega (alpha della lega) | **Q5** | 351 | 0.6006 | 0.5698 | +0.0308 |


## 4. Verdetto e regola d'arresto

Criterio: un NegBin 'batte' il Poisson solo se il Δ Brier aggregato e' negativo con IC 95% interamente sotto zero su VALIDATION **e** TEST, la LogLoss non peggiora in modo significativo, e almeno 3 leghe su 5 sono negative in entrambi gli split senza inversioni significative per lega. Simmetricamente si segnala un peggioramento coerente.

- 1X2, NB-pooled (alpha unico 5 leghe): ΔBrier validation -0.0160 [-0.0189; -0.0131], test -0.0147 [-0.0176; -0.0119]; leghe con Δ negativo in entrambi gli split 5/5, con Δ positivo in entrambi 0/5; celle lega-split significativamente PEGGIORI 0 -> **MIGLIORAMENTO COERENTE**
- 1X2, NB-per-lega (alpha della lega): ΔBrier validation -0.0160 [-0.0188; -0.0131], test -0.0147 [-0.0176; -0.0120]; leghe con Δ negativo in entrambi gli split 5/5, con Δ positivo in entrambi 0/5; celle lega-split significativamente PEGGIORI 0 -> **MIGLIORAMENTO COERENTE**
- O/U2.5, NB-pooled (alpha unico 5 leghe): ΔBrier validation -0.0050 [-0.0066; -0.0034], test -0.0040 [-0.0057; -0.0025]; leghe con Δ negativo in entrambi gli split 5/5, con Δ positivo in entrambi 0/5; celle lega-split significativamente PEGGIORI 0 -> **MIGLIORAMENTO COERENTE**
- O/U2.5, NB-per-lega (alpha della lega): ΔBrier validation -0.0050 [-0.0067; -0.0034], test -0.0039 [-0.0055; -0.0023]; leghe con Δ negativo in entrambi gli split 5/5, con Δ positivo in entrambi 0/5; celle lega-split significativamente PEGGIORI 0 -> **MIGLIORAMENTO COERENTE**
- GG/NG, NB-pooled (alpha unico 5 leghe): ΔBrier validation +0.0056 [0.0033; 0.0078], test +0.0057 [0.0035; 0.0079]; leghe con Δ negativo in entrambi gli split 0/5, con Δ positivo in entrambi 5/5; celle lega-split significativamente PEGGIORI 4 -> **PEGGIORAMENTO COERENTE**
- GG/NG, NB-per-lega (alpha della lega): ΔBrier validation +0.0053 [0.0029; 0.0076], test +0.0055 [0.0033; 0.0076]; leghe con Δ negativo in entrambi gli split 0/5, con Δ positivo in entrambi 5/5; celle lega-split significativamente PEGGIORI 4 -> **PEGGIORAMENTO COERENTE**

Evidenza dal lato della stima:

- testa 1X2 (NORM-SUM xG+forma+mercato): alpha pooled 0.21904 con IC [0.18843; 0.25193] (0% dei bootstrap al confine alpha=0); alpha per-lega da 0.14776 a 0.29767.
- testa Totali (modello B, lambda puri): alpha pooled 0.18911 con IC [0.15567; 0.22190] (0% dei bootstrap al confine alpha=0); alpha per-lega da 0.14345 a 0.25376.

### VERDETTO: overdispersion condizionale **DIMOSTRATA**, ma la NegBin NON e' una correzione universale

La regola d'arresto NON scatta: a differenza dei tentativi fatti sulla media aggregata, condizionando la varianza al lambda per-partita emergono alpha grandi e lontani dal confine Poisson sotto bootstrap (0% di resample al confine zero), e i mercati **1X2, O/U2.5** migliorano in modo coerente su validation e test, aggregate e per lega, sia Brier sia LogLoss. Il quadro e' pero' monco e va scritto senza scontorni:

1. **Cosa vince**. 1X2 (testa Poisson pura, senza Elo): ΔBrier -0.0160 [-0.0189; -0.0131] su validation e -0.0147 [-0.0176; -0.0119] su test (5 leghe su 5 negative in entrambi gli split); O/U2.5: -0.0050 [-0.0066; -0.0034] e -0.0040 [-0.0057; -0.0025], di nuovo 5/5. I miglioramenti di LogLoss sono piu' grandi di quelli di Brier: e' il segno atteso quando si correggono le code.
2. **Cosa perde, in modo altrettanto coerente: GG/NG**. ΔBrier +0.0056 [0.0033; 0.0078] su validation e +0.0057 [0.0035; 0.0079] su test (ΔLogLoss +0.0131 su validation, +0.0128 su test); per-lega il delta Brier e' positivo in 10/10 celle lega×split, 4/10 fuori IC, mai negativo in modo significativo. Il motivo e' strutturale e si vede nella diagnostica §1: la sovra-dispersione reale e' ASIMMETRICA, ci sono code alte ma NON ci sono piu' zeri del Poisson (anzi: P(0) osservata 0.25-0.26 contro 0.31-0.35 del Poisson), mentre la NB2 aggiunge massa anche sullo zero (P(0)=(1+alpha*lambda)^(-1/alpha), portandola a 0.35-0.38): abbassa quindi troppo P(GG). La forma di coda imposta da Var=lambda+alpha*lambda^2 e' giusta per le soglie alte del risultato e del totale, sbagliata per l'evento 'entrambe segnano'. Un solo alpha non puo' vincere tutti i mercati: la sovra-dispersione reale non ha esattamente forma NB2.
3. **Pooled e per-lega sono indistinguibili** (gli IC dei delta si sovrappongono riga per riga, e i delta sono identici fino alla 4ª cifra): non c'e' struttura per lega nella sovra-dispersione, confermando che alpha descrive una proprieta' della legge di conteggio, non un campionato. Non giustifica 5 parametri in piu'.
4. **Dove nasce il guadagno: le code degli affidabilita' (§3)**. Il Poisson e' troppo sicuro ai due estremi: coda bassa che osserva molto di piu' di quanto prometta e coda alta che promette troppo (esattamente la patologia trovata dall'audit combo, Q5 che prometteva 0.65 e realizzava 0.40). La NB2 ritrae le probabilita' estreme verso il centro: sulle code di casa, trasferta e Over il bias assoluto del Q5 (e quasi sempre del Q1) si riduce in entrambi gli split (es. Over Q5 test: +0.164 Poisson, +0.107 NB; casa Q5 validation: +0.223, +0.171); il pareggio e' l'eccezione, col suo Q5 che peggiora lievemente. Su GG, invece, lo stesso ritiro peggiora il Q1 (gia' gravemente sottopredetto) e non basta mai: il difetto di GG e' di LIVELLO (le frequenze osservate nei quintili bassi sono largamente sopra la predizione anche col Poisson), non di varianza.
5. **Cosa questo audit NON dimostra**. La testa 1X2 mostrata in produzione e' il blend con Elo (w=0.25), non il Poisson puro qui confrontato: non e' detto che l'alpha che migliora il Poisson migliori il blend (l'Elo corregge gia' parte di overconfidenza); andrebbe ripetuto l'1X2 con la marginale NB dentro il blend. I lambda della testa Totali sono quelli da snapshot xG statico dell'audit di riferimento, non la fonte point-in-time live. Infine i grandi bias di LIVELLO nei Q1 (Over predetto 0.25 e osservato 0.50) restano presenti in tutte le versioni: l'NB2 lavora sulla dispersione, non azzera gli errori di livello del motore di audit.

**Conclusione operativa**: la risposta alla domanda e' SI', i gol realizzati sono piu' dispersi del Poisson condizionato al lambda per-partita (alpha ~0.2, IC lontano da zero, robusto alle righe estreme, stabile tra validation e test), ma in forma diversa da una NB2 unica: quel modello e' un miglioramento per 1X2 e Over/Under e un danno per GG/NG, quindi non se ne autorizza l'adozione in blocco. Se si vorra' sfruttare il segnale, la strada e' una correzione di coda applicata alle soglie (1X2, totali alti) lasciando GG al Poisson (o un modello di coda piu' flessibile di NB2, es. mistura o correzioni di livello), ripetendo il walk-forward con la marginale dentro il blend Elo e su snapshot successivi. Questo script, come da disciplina, misura e non modifica: nessun intervento su SoccerMath/ e' raccomandato qui.

*Mercati a peggioramento coerente: GG/NG (NB-pooled e NB-per-lega); la regola d'arresto ('overdispersion non dimostrata') non si applica perche' esistono anche i miglioramenti elencati al punto 1.*

## Limiti dichiarati

1. **Alpha unico per tutti i livelli di lambda**: l'NB2 impone Var = lambda + alpha*lambda^2 con un solo alpha; una overdispersion locale (es. solo sulle partite molto aperte) non sarebbe catturata. Le tabelle descrittive §1 e i quintili §3 servono anche a rivelarlo.
2. **Indipendenza casa/trasferta mantenuta**: si sostituisce solo la pmf marginale; la dipendenza tra i due conteggi (tau Dixon-Coles, correlazione delle combo) e' fuori campo.
3. **Lambda da snapshot xG statico per la testa Totali** (come in `diagnose_form_totali`/combo): ne eredita i limiti gia' dichiarati. In piu' la diagnostica §1 mostra che i lambda di questo walk-forward sono troppo sparpagliati (P(0) marginale sovrastimata via Jensen): parte dell'alpha MLE assorbe quella misspecificazione oltre alla coda reale. Il confronto Poisson vs NegBin usa gli stessi identici lambda, quindi la conclusione RELATIVA (NB2 migliore/peggiore, mercato per mercato) resta valida per questo motore; il valore assoluto di alpha non e' trapiantabile sulla fonte point-in-time di produzione senza ripetere la stima.
4. **Alpha al confine**: il parametro alpha dell'NB2 non puo' essere negativo (sotto-dispersione non ammessa da questa famiglia); quando il MLE cerca alpha=0 gli IC bootstrap si accalorano sul confine e vanno letti come 'nessun guadagno rispetto al Poisson', non come stima puntuale precisa di uno zero.
5. **Unico snapshot temporale** (2026-09): gli alpha sono direzione storica, non coefficienti da cablare; il verdetto fuori-campione su due stagioni e' la parte che conta.
6. **Solo calibrazione, niente quote per questi mercati in questo script**: ci si limita a Brier/LogLoss/affidabilita'; non si misura ROI.
7. **NB2 non e' onnipotente sulle code**: aggiungere massa sullo zero e sulle code alte e' un unico movimento parametrizzato; il conflitto 1X2/Over (migliora) contro GG (peggiora) mostra che la vera deviazione dal Poisson non ha esattamente questa forma. Inoltre la NB2 corregge la dispersione ma non il LIVELLO: i bias di livello residui nei quintili bassi (§3) restano e chiedono interventi diversi (calibrazione delle marginali, fonte xG point-in-time).
8. **La testa 1X2 di produzione e' blendata con Elo**: il confronto e' contro il Poisson puro della testa; un eventuale deployment dovrebbe prima verificare la marginale NB dentro il blend, non il sostituto del blend.

## Riferimenti incrociati

- `audit/results/elo_ensemble_diagnosis.md`: testa 1X2 di riferimento;
- `audit/results/form_totali_diagnosis.md`: testa Totali modello B;
- `audit/results/combo_1x2_totali_diagnosis.md`: walk-forward e cross-check bit-a-bit qui riutilizzati, e lente a quintili;
- `audit/results/dixon_coles_rho_diagnosis.md`: schema pooled vs per-lega di un unico parametro stimato sul train.

