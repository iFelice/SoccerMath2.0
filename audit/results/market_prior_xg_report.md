# Prior xG derivato dai dati vs tabella MARKET_VALUES (walk-forward, 1X2)

Generato: 2026-10-06T21:28:11+00:00
Protocollo: identico a `market_values_versioned.py` (11/09/2026): walker condiviso, testa NORM-SUM + Elo 0.6/0.4, VALIDATION 2024/25, TEST 2025/26, bootstrap appaiato 2000 resample seed 20260905. Stake 10, edge>0 vs fair de-vigata.

## Variante pre-registrata XGP

`q = (10·0.65·xGD_prev + n_cur·xGD_cur) / (10 + n_cur)`, `factor = clip(1 + 0.25·q, 0.85, 1.25)`. Squadre promosse: xGD_prev = media delle retrocesse che sostituiscono. Point-in-time: solo partite con kickoff nel giorno precedente a quello valutato.

Uso del prior (slot squadra-partita valutati): previous_season 5984, promoted 1024, no_history 0, n_cur_sum 124754, slots 7008

## Riproduzione del riferimento 11/09 (STATIC / VER / NONE)

I valori STATIC/VER/NONE devono coincidere con `market_values_versioned_report.md`: stessa passata, stesso codice.

## VALIDATION 2024/25 — aggregato 5 leghe

| variante | n | Brier | LogLoss | Brier blend | LogLoss blend | ROI B365 | n bet | ROI Avg |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| static | 1752 | 0.6247 | 1.0705 | 0.5890 | 0.9893 | -1.76% | 1699 | -2.34% |
| ver | 1752 | 0.6246 | 1.0703 | 0.5891 | 0.9895 | -1.70% | 1686 | -3.57% |
| none | 1752 | 0.6299 | 1.0728 | 0.5907 | 0.9919 | -4.15% | 1682 | -3.95% |
| xgp | 1752 | 0.6249 | 1.0741 | 0.5884 | 0.9883 | -0.44% | 1699 | 0.57% |

Delta appaiati (variante − static), CI bootstrap 95%:

| coppia | Brier | LogLoss | ROI B365 (punti %) |
|---|---|---|---|
| xgp-static | +0.0002 [-0.0031; +0.0034] n.s. | +0.0036 [-0.0018; +0.0093] n.s. | +1.3196 [-1.7804; +4.3609] n.s. |
| ver-static | -0.0000 [-0.0013; +0.0013] n.s. | -0.0002 [-0.0023; +0.0020] n.s. | +0.0606 [-1.8309; +2.0087] n.s. |
| none-static | +0.0052 [+0.0015; +0.0088] **sig.** | +0.0023 [-0.0042; +0.0088] n.s. | -2.3900 [-6.3562; +1.8716] n.s. |
| xgp-none | -0.0050 [-0.0099; +0.0003] n.s. | +0.0013 [-0.0080; +0.0107] n.s. | +3.7096 [-1.0670; +8.3038] n.s. |

## TEST 2025/26 — aggregato 5 leghe

| variante | n | Brier | LogLoss | Brier blend | LogLoss blend | ROI B365 | n bet | ROI Avg |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| static | 1752 | 0.6240 | 1.0609 | 0.5904 | 0.9913 | 5.46% | 1676 | 2.81% |
| ver | 1752 | 0.6237 | 1.0602 | 0.5902 | 0.9912 | 4.37% | 1685 | 2.25% |
| none | 1752 | 0.6253 | 1.0572 | 0.5909 | 0.9923 | 2.83% | 1682 | 2.74% |
| xgp | 1752 | 0.6291 | 1.0722 | 0.5908 | 0.9918 | 5.33% | 1695 | 3.85% |

Delta appaiati (variante − static), CI bootstrap 95%:

| coppia | Brier | LogLoss | ROI B365 (punti %) |
|---|---|---|---|
| xgp-static | +0.0051 [+0.0018; +0.0085] **sig.** | +0.0113 [+0.0058; +0.0172] **sig.** | -0.1326 [-3.8353; +3.2317] n.s. |
| ver-static | -0.0004 [-0.0021; +0.0015] n.s. | -0.0007 [-0.0036; +0.0024] n.s. | -1.0933 [-3.5171; +1.1919] n.s. |
| none-static | +0.0013 [-0.0025; +0.0052] n.s. | -0.0037 [-0.0104; +0.0029] n.s. | -2.6342 [-6.7219; +1.5903] n.s. |
| xgp-none | +0.0038 [-0.0011; +0.0085] n.s. | +0.0150 [+0.0062; +0.0238] **sig.** | +2.5016 [-2.2981; +6.9676] n.s. |

## Per lega (XGP − STATIC, delta appaiati con CI 95%)

| lega | split | n | Brier static | Brier xgp | Δ Brier | Δ LogLoss | ROI B365 static | ROI B365 xgp | Δ ROI B365 |
|---|---|---:|---:|---:|---|---|---:|---:|---|
| Serie A | val | 380 | 0.6352 | 0.6311 | -0.0041 [-0.0103; +0.0018] n.s. | -0.0077 [-0.0186; +0.0025] n.s. | -8.63% | -8.48% | +0.1522 [-5.6042; +5.7452] n.s. |
| Serie A | test | 380 | 0.6100 | 0.6127 | +0.0027 [-0.0036; +0.0087] n.s. | +0.0055 [-0.0054; +0.0161] n.s. | 9.94% | 11.96% | +2.0233 [-4.4860; +8.3573] n.s. |
| Premier League | val | 380 | 0.6158 | 0.6113 | -0.0044 [-0.0131; +0.0046] n.s. | -0.0033 [-0.0177; +0.0118] n.s. | -2.54% | 3.23% | +5.7762 [-2.3807; +14.0825] n.s. |
| Premier League | test | 380 | 0.6451 | 0.6534 | +0.0083 [-0.0004; +0.0167] n.s. | +0.0151 [+0.0017; +0.0286] **sig.** | 15.08% | 14.47% | -0.6085 [-7.7003; +7.0537] n.s. |
| La Liga | val | 380 | 0.5961 | 0.6001 | +0.0040 [-0.0014; +0.0091] n.s. | +0.0139 [+0.0035; +0.0238] **sig.** | 1.94% | 3.71% | +1.7726 [-4.9155; +8.1048] n.s. |
| La Liga | test | 380 | 0.6172 | 0.6242 | +0.0070 [-0.0004; +0.0143] n.s. | +0.0143 [+0.0013; +0.0275] **sig.** | -12.14% | -9.61% | +2.5325 [-4.9750; +9.8196] n.s. |
| Bundesliga | val | 306 | 0.6558 | 0.6583 | +0.0025 [-0.0043; +0.0096] n.s. | +0.0061 [-0.0049; +0.0178] n.s. | 4.25% | 5.57% | +1.3140 [-3.2165; +6.0133] n.s. |
| Bundesliga | test | 306 | 0.6221 | 0.6250 | +0.0029 [-0.0032; +0.0093] n.s. | +0.0152 [+0.0037; +0.0276] **sig.** | 5.01% | 4.99% | -0.0199 [-8.6040; +7.1694] n.s. |
| Ligue 1 | val | 306 | 0.6271 | 0.6312 | +0.0041 [-0.0045; +0.0130] n.s. | +0.0108 [-0.0038; +0.0256] n.s. | -2.99% | -6.04% | -3.0539 [-11.8123; +4.8845] n.s. |
| Ligue 1 | test | 306 | 0.6256 | 0.6293 | +0.0036 [-0.0046; +0.0122] n.s. | +0.0060 [-0.0073; +0.0201] n.s. | 10.77% | 5.04% | -5.7282 [-18.2462; +3.9152] n.s. |

## Sensibilita' ai parametri (solo trasparenza, NON usata per decidere)

Brier aggregato della testa Poisson; la variante pre-registrata e' `xgp`.

| variante | Brier V | Brier T | ROI B365 V | ROI B365 T |
|---|---:|---:|---:|---:|
| xgp | 0.6249 | 0.6291 | -0.44% | 5.33% |
| xgp_p0.5_m6_s0.15 | 0.6249 | 0.6270 | -1.17% | 5.11% |
| xgp_p0.5_m6_s0.25 | 0.6255 | 0.6297 | -1.25% | 5.99% |
| xgp_p0.5_m6_s0.35 | 0.6265 | 0.6313 | 0.48% | 3.78% |
| xgp_p0.5_m10_s0.15 | 0.6249 | 0.6265 | -1.86% | 5.02% |
| xgp_p0.5_m10_s0.25 | 0.6249 | 0.6291 | -0.81% | 5.69% |
| xgp_p0.5_m10_s0.35 | 0.6257 | 0.6304 | -0.18% | 6.25% |
| xgp_p0.5_m19_s0.15 | 0.6251 | 0.6260 | -1.05% | 5.21% |
| xgp_p0.5_m19_s0.25 | 0.6245 | 0.6282 | -0.91% | 5.50% |
| xgp_p0.5_m19_s0.35 | 0.6248 | 0.6296 | 0.07% | 6.21% |
| xgp_p0.65_m6_s0.15 | 0.6246 | 0.6270 | -1.16% | 4.57% |
| xgp_p0.65_m6_s0.25 | 0.6254 | 0.6296 | -0.86% | 5.96% |
| xgp_p0.65_m6_s0.35 | 0.6264 | 0.6311 | 0.15% | 4.85% |
| xgp_p0.65_m10_s0.15 | 0.6246 | 0.6265 | -1.41% | 4.44% |
| xgp_p0.65_m10_s0.35 | 0.6256 | 0.6304 | -0.26% | 5.95% |
| xgp_p0.65_m19_s0.15 | 0.6247 | 0.6260 | -0.47% | 5.31% |
| xgp_p0.65_m19_s0.25 | 0.6244 | 0.6284 | -0.22% | 5.04% |
| xgp_p0.65_m19_s0.35 | 0.6249 | 0.6298 | 0.67% | 5.41% |
| xgp_p0.8_m6_s0.15 | 0.6244 | 0.6270 | -0.98% | 5.12% |
| xgp_p0.8_m6_s0.25 | 0.6253 | 0.6296 | -0.85% | 5.54% |
| xgp_p0.8_m6_s0.35 | 0.6263 | 0.6311 | 0.59% | 4.88% |
| xgp_p0.8_m10_s0.15 | 0.6243 | 0.6266 | -1.22% | 5.62% |
| xgp_p0.8_m10_s0.25 | 0.6248 | 0.6290 | -0.44% | 6.10% |
| xgp_p0.8_m10_s0.35 | 0.6256 | 0.6305 | 0.13% | 5.24% |
| xgp_p0.8_m19_s0.15 | 0.6245 | 0.6262 | 0.07% | 4.98% |
| xgp_p0.8_m19_s0.25 | 0.6245 | 0.6286 | 0.62% | 4.38% |
| xgp_p0.8_m19_s0.35 | 0.6250 | 0.6301 | 0.97% | 3.73% |

## Decisione

- aggregato val brier: Δ(xgp−static) +0.0002 CI [-0.0031; +0.0034] → n.s.
- aggregato val log_loss: Δ(xgp−static) +0.0036 CI [-0.0018; +0.0093] → n.s.
- aggregato val roi_b365: Δ(xgp−static) +1.3196 CI [-1.7804; +4.3609] → n.s.
- aggregato test brier: Δ(xgp−static) +0.0051 CI [+0.0018; +0.0085] → PEGGIORA (sig.)
- aggregato test log_loss: Δ(xgp−static) +0.0113 CI [+0.0058; +0.0172] → PEGGIORA (sig.)
- aggregato test roi_b365: Δ(xgp−static) -0.1326 CI [-3.8353; +3.2317] → n.s.

**Esito: TENERE la tabella MARKET_VALUES: il prior xG peggiora in modo significativo aggregato test brier; aggregato test log_loss**

## Lettura

- Robustezza del verdetto: su 27 configurazioni della griglia (persistence x prior_matches x slope), 8 battono la tabella su VALIDATION e **0 su TEST** (Brier testa Poisson). Il risultato non dipende dalla scelta dei parametri pre-registrati.
- Il prior xG e' competitivo con la tabella in VALIDATION (Brier identico, ROI n.s.) e migliore di NONE, ma in TEST perde cio' che la tabella conserva: lo xGD della stagione precedente non vede i cambi di rosa del mercato estivo (cessioni/acquisti, neopromosse con investimenti), che il valore di rosa incorpora per costruzione. Con ~10 partite di stagione corrente il prior converge verso lo xGD corrente, gia' rappresentato nella testa dal fattore forma e dallo snapshot xG: informazione ridondante, non aggiuntiva.
- ROI B365: nessuna differenza significativa in nessun confronto (CI larghe ±3-7 punti): il ROI non discrimina fra le varianti, la decisione poggia su Brier/LogLoss come da protocollo.
- Nota di protocollo (ereditata dall'11/09): la testa usa lo snapshot xG CORRENTE `xg_<lega>.json` come forza primaria per tutte le stagioni, quindi i valori assoluti cambiano a ogni aggiornamento dello snapshot (STATIC V 0.6522 -> 0.6398 fra 11/09 e oggi). I confronti restano appaiati e validi; i numeri assoluti non sono confrontabili fra referti di date diverse.
- Conseguenza operativa per il rollover: `config.MARKET_VALUES` resta la fonte del fattore mercato; al rollover non blocca nulla (squadre assenti -> default 50, fattore 0.925) e `season_rollover.py` segnala le squadre del Live prive di valore, cosi' l'aggiornamento estivo della tabella e' un avviso esplicito e non una scoperta tardiva.
