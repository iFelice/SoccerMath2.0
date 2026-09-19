# Prior xG derivato dai dati vs tabella MARKET_VALUES (walk-forward, 1X2)

Generato: 2026-09-19T22:12:49+00:00  
Protocollo: identico a `market_values_versioned.py` (11/09/2026): walker condiviso, testa NORM-SUM + Elo 0.6/0.4, VALIDATION 2024/25, TEST 2025/26, bootstrap appaiato 2000 resample seed 20260905. Stake 10, edge>0 vs fair de-vigata.

## Variante pre-registrata XGP

`q = (10·0.65·xGD_prev + n_cur·xGD_cur) / (10 + n_cur)`, `factor = clip(1 + 0.25·q, 0.85, 1.25)`. Squadre promosse: xGD_prev = media delle retrocesse che sostituiscono. Point-in-time: solo partite con kickoff nel giorno precedente a quello valutato.

Uso del prior (slot squadra-partita valutati): previous_season 5984, promoted 1024, no_history 0, n_cur_sum 124754, slots 7008

## Riproduzione del riferimento 11/09 (STATIC / VER / NONE)

I valori STATIC/VER/NONE devono coincidere con `market_values_versioned_report.md`: stessa passata, stesso codice.

## VALIDATION 2024/25 — aggregato 5 leghe

| variante | n | Brier | LogLoss | Brier blend | LogLoss blend | ROI B365 | n bet | ROI Avg |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| static | 1752 | 0.6398 | 1.0988 | 0.5911 | 0.9922 | -2.61% | 1752 | -1.30% |
| ver | 1752 | 0.6398 | 1.0985 | 0.5912 | 0.9923 | -2.13% | 1752 | -1.57% |
| none | 1752 | 0.6449 | 1.0997 | 0.5928 | 0.9947 | 0.34% | 1752 | 0.52% |
| xgp | 1752 | 0.6398 | 1.1021 | 0.5905 | 0.9912 | 0.28% | 1752 | 1.42% |

Delta appaiati (variante − static), CI bootstrap 95%:

| coppia | Brier | LogLoss | ROI B365 (punti %) |
|---|---|---|---|
| xgp-static | -0.0000 [-0.0031; +0.0032] n.s. | +0.0033 [-0.0022; +0.0092] n.s. | +2.8916 [-0.8527; +6.6096] n.s. |
| ver-static | -0.0001 [-0.0013; +0.0012] n.s. | -0.0003 [-0.0024; +0.0020] n.s. | +0.4789 [-1.7854; +2.8082] n.s. |
| none-static | +0.0051 [+0.0015; +0.0089] **sig.** | +0.0010 [-0.0055; +0.0075] n.s. | +2.9555 [-0.9589; +7.3938] n.s. |
| xgp-none | -0.0051 [-0.0100; +0.0001] n.s. | +0.0023 [-0.0070; +0.0119] n.s. | -0.0639 [-4.8328; +4.3836] n.s. |

## TEST 2025/26 — aggregato 5 leghe

| variante | n | Brier | LogLoss | Brier blend | LogLoss blend | ROI B365 | n bet | ROI Avg |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| static | 1752 | 0.6335 | 1.0802 | 0.5908 | 0.9919 | 2.80% | 1752 | 2.04% |
| ver | 1752 | 0.6329 | 1.0788 | 0.5906 | 0.9917 | 2.41% | 1752 | 2.60% |
| none | 1752 | 0.6347 | 1.0754 | 0.5912 | 0.9926 | 5.72% | 1752 | 5.31% |
| xgp | 1752 | 0.6377 | 1.0906 | 0.5911 | 0.9923 | 2.90% | 1752 | 2.26% |

Delta appaiati (variante − static), CI bootstrap 95%:

| coppia | Brier | LogLoss | ROI B365 (punti %) |
|---|---|---|---|
| xgp-static | +0.0042 [+0.0011; +0.0075] **sig.** | +0.0105 [+0.0051; +0.0164] **sig.** | +0.0976 [-2.9640; +3.2626] n.s. |
| ver-static | -0.0007 [-0.0024; +0.0013] n.s. | -0.0013 [-0.0043; +0.0018] n.s. | -0.3967 [-2.8545; +2.1421] n.s. |
| none-static | +0.0012 [-0.0025; +0.0050] n.s. | -0.0047 [-0.0114; +0.0018] n.s. | +2.9161 [-1.1433; +7.0628] n.s. |
| xgp-none | +0.0030 [-0.0017; +0.0078] n.s. | +0.0152 [+0.0065; +0.0239] **sig.** | -2.8185 [-7.2643; +1.4994] n.s. |

## Per lega (XGP − STATIC, delta appaiati con CI 95%)

| lega | split | n | Brier static | Brier xgp | Δ Brier | Δ LogLoss | ROI B365 static | ROI B365 xgp | Δ ROI B365 |
|---|---|---:|---:|---:|---|---|---:|---:|---|
| Serie A | val | 380 | 0.6514 | 0.6481 | -0.0033 [-0.0092; +0.0023] n.s. | -0.0070 [-0.0182; +0.0034] n.s. | -8.23% | -3.24% | +4.9895 [-0.5000; +10.9263] n.s. |
| Serie A | test | 380 | 0.6210 | 0.6241 | +0.0031 [-0.0030; +0.0088] n.s. | +0.0063 [-0.0047; +0.0171] n.s. | 9.28% | 7.60% | -1.6763 [-8.4947; +4.9368] n.s. |
| Premier League | val | 380 | 0.6324 | 0.6275 | -0.0050 [-0.0137; +0.0040] n.s. | -0.0030 [-0.0174; +0.0122] n.s. | -2.79% | 0.48% | +3.2763 [-8.1184; +13.3605] n.s. |
| Premier League | test | 380 | 0.6529 | 0.6607 | +0.0078 [-0.0009; +0.0162] n.s. | +0.0160 [+0.0028; +0.0295] **sig.** | 13.79% | 13.71% | -0.0868 [-7.6342; +7.6263] n.s. |
| La Liga | val | 380 | 0.6090 | 0.6118 | +0.0029 [-0.0024; +0.0080] n.s. | +0.0122 [+0.0017; +0.0221] **sig.** | -2.23% | 0.09% | +2.3237 [-5.5632; +10.0526] n.s. |
| La Liga | test | 380 | 0.6239 | 0.6296 | +0.0058 [-0.0015; +0.0130] n.s. | +0.0125 [-0.0005; +0.0256] n.s. | -8.09% | -7.85% | +0.2395 [-7.5132; +8.0816] n.s. |
| Bundesliga | val | 306 | 0.6688 | 0.6718 | +0.0030 [-0.0033; +0.0097] n.s. | +0.0062 [-0.0052; +0.0186] n.s. | 4.76% | 7.44% | +2.6863 [-3.6699; +8.9477] n.s. |
| Bundesliga | test | 306 | 0.6434 | 0.6445 | +0.0011 [-0.0048; +0.0068] n.s. | +0.0132 [+0.0018; +0.0255] **sig.** | -0.38% | 1.24% | +1.6144 [-2.7974; +5.7745] n.s. |
| Ligue 1 | val | 306 | 0.6441 | 0.6478 | +0.0037 [-0.0049; +0.0127] n.s. | +0.0099 [-0.0048; +0.0249] n.s. | -3.26% | -2.55% | +0.7190 [-9.2614; +10.0458] n.s. |
| Ligue 1 | test | 306 | 0.6273 | 0.6295 | +0.0022 [-0.0053; +0.0103] n.s. | +0.0035 [-0.0094; +0.0174] n.s. | -2.19% | -1.35% | +0.8366 [-7.1046; +9.0098] n.s. |

## Sensibilita' ai parametri (solo trasparenza, NON usata per decidere)

Brier aggregato della testa Poisson; la variante pre-registrata e' `xgp`.

| variante | Brier V | Brier T | ROI B365 V | ROI B365 T |
|---|---:|---:|---:|---:|
| xgp | 0.6398 | 0.6377 | 0.28% | 2.90% |
| xgp_p0.5_m6_s0.15 | 0.6397 | 0.6360 | 0.93% | 3.53% |
| xgp_p0.5_m6_s0.25 | 0.6404 | 0.6384 | 0.55% | 2.77% |
| xgp_p0.5_m6_s0.35 | 0.6415 | 0.6399 | 0.02% | 0.59% |
| xgp_p0.5_m10_s0.15 | 0.6398 | 0.6355 | 0.41% | 3.41% |
| xgp_p0.5_m10_s0.25 | 0.6399 | 0.6378 | 0.35% | 4.12% |
| xgp_p0.5_m10_s0.35 | 0.6406 | 0.6390 | -0.20% | 1.32% |
| xgp_p0.5_m19_s0.15 | 0.6401 | 0.6349 | 0.16% | 3.82% |
| xgp_p0.5_m19_s0.25 | 0.6395 | 0.6369 | 0.13% | 3.21% |
| xgp_p0.5_m19_s0.35 | 0.6398 | 0.6382 | -0.29% | 1.47% |
| xgp_p0.65_m6_s0.15 | 0.6395 | 0.6359 | 0.46% | 3.26% |
| xgp_p0.65_m6_s0.25 | 0.6404 | 0.6383 | 0.33% | 2.71% |
| xgp_p0.65_m6_s0.35 | 0.6414 | 0.6397 | -0.54% | 2.20% |
| xgp_p0.65_m10_s0.15 | 0.6395 | 0.6354 | 0.39% | 3.29% |
| xgp_p0.65_m10_s0.35 | 0.6406 | 0.6390 | -0.33% | 1.65% |
| xgp_p0.65_m19_s0.15 | 0.6397 | 0.6349 | 0.37% | 3.44% |
| xgp_p0.65_m19_s0.25 | 0.6395 | 0.6370 | -0.08% | 2.50% |
| xgp_p0.65_m19_s0.35 | 0.6399 | 0.6383 | -0.36% | 2.43% |
| xgp_p0.8_m6_s0.15 | 0.6393 | 0.6358 | 0.47% | 3.30% |
| xgp_p0.8_m6_s0.25 | 0.6403 | 0.6382 | 0.53% | 1.97% |
| xgp_p0.8_m6_s0.35 | 0.6413 | 0.6397 | -0.28% | 2.15% |
| xgp_p0.8_m10_s0.15 | 0.6392 | 0.6354 | 0.46% | 3.22% |
| xgp_p0.8_m10_s0.25 | 0.6399 | 0.6377 | 0.43% | 3.06% |
| xgp_p0.8_m10_s0.35 | 0.6406 | 0.6390 | -0.46% | 2.51% |
| xgp_p0.8_m19_s0.15 | 0.6395 | 0.6349 | 0.88% | 3.27% |
| xgp_p0.8_m19_s0.25 | 0.6396 | 0.6371 | -0.42% | 3.35% |
| xgp_p0.8_m19_s0.35 | 0.6400 | 0.6385 | -0.79% | 2.47% |

## Decisione

- aggregato val brier: Δ(xgp−static) -0.0000 CI [-0.0031; +0.0032] → n.s.
- aggregato val log_loss: Δ(xgp−static) +0.0033 CI [-0.0022; +0.0092] → n.s.
- aggregato val roi_b365: Δ(xgp−static) +2.8916 CI [-0.8527; +6.6096] → n.s.
- aggregato test brier: Δ(xgp−static) +0.0042 CI [+0.0011; +0.0075] → PEGGIORA (sig.)
- aggregato test log_loss: Δ(xgp−static) +0.0105 CI [+0.0051; +0.0164] → PEGGIORA (sig.)
- aggregato test roi_b365: Δ(xgp−static) +0.0976 CI [-2.9640; +3.2626] → n.s.

**Esito: TENERE la tabella MARKET_VALUES: il prior xG peggiora in modo significativo aggregato test brier; aggregato test log_loss**

## Lettura

- Robustezza del verdetto: su 27 configurazioni della griglia (persistence x prior_matches x slope), 10 battono la tabella su VALIDATION e **0 su TEST** (Brier testa Poisson). Il risultato non dipende dalla scelta dei parametri pre-registrati.
- Il prior xG e' competitivo con la tabella in VALIDATION (Brier identico, ROI n.s.) e migliore di NONE, ma in TEST perde cio' che la tabella conserva: lo xGD della stagione precedente non vede i cambi di rosa del mercato estivo (cessioni/acquisti, neopromosse con investimenti), che il valore di rosa incorpora per costruzione. Con ~10 partite di stagione corrente il prior converge verso lo xGD corrente, gia' rappresentato nella testa dal fattore forma e dallo snapshot xG: informazione ridondante, non aggiuntiva.
- ROI B365: nessuna differenza significativa in nessun confronto (CI larghe ±3-7 punti): il ROI non discrimina fra le varianti, la decisione poggia su Brier/LogLoss come da protocollo.
- Nota di protocollo (ereditata dall'11/09): la testa usa lo snapshot xG CORRENTE `xg_<lega>.json` come forza primaria per tutte le stagioni, quindi i valori assoluti cambiano a ogni aggiornamento dello snapshot (STATIC V 0.6522 -> 0.6398 fra 11/09 e oggi). I confronti restano appaiati e validi; i numeri assoluti non sono confrontabili fra referti di date diverse.
- Conseguenza operativa per il rollover: `config.MARKET_VALUES` resta la fonte del fattore mercato; al rollover non blocca nulla (squadre assenti -> default 50, fattore 0.925) e `season_rollover.py` segnala le squadre del Live prive di valore, cosi' l'aggiornamento estivo della tabella e' un avviso esplicito e non una scoperta tardiva.
