# Modello contro mercato sull'1X2 — referto di audit (sola lettura)

Generato da `audit/onex2_market_test.py` (nessuna modifica a `SoccerMath/`). Commit di base: `06ffaf326b8b3cc8970705fea1b0f1c29e4b04e8` (branch `arena/944a1c7e-soccermath2-0`); origin/main: `a16284c09b50668e54cae625b9b0a40c691a665b`. Bootstrap: 2000 repliche a blocchi (lega × stagione × giornata), seme 20261008. Tempo di esecuzione: 294 s.
Comando: `python audit/onex2_market_test.py`.

## 0. Fonti di probabilita' e verifiche di riuso

| Fonte | Codice riusato (non riscritto) | Note |
|---|---|---|
| Modello blend | `app.blend_elo_into_1x2(..., w=app.POISSON_1X2_WEIGHT)` | w = 0.25; identita' w·Poisson+(1−w)·Elo verificata in §0 (scarto max sotto) |
| Poisson puro | `ppda_residual_test.production_totali` + intercettazione di `app.get_full_poisson_two_heads` | 1X2 raccolte nell'ordine del banco; parita' con `engine_u25`/`engine_gg` (vedi sotto) |
| Elo puro | `elo_walker_core.build_walker_table` → `EloEngine` (seeding S3, `PROMOTED_SEED_OFFSET`) | rating prima della partita; aggiornamento dopo |
| De-vig proporzionale | `backtest_experiment_all.devig_1x2` | decisione della commessa |
| De-vig Shin | `devig_shin3` (in questo script, 3 esiti) | sensibilita'; verifica somma=1 nei test |
| Base rate | stagioni precedenti della lega (come `baserate_oos.raw`, PR #34) | train 2022/23… (vedi JSON) |

Verifiche di parita' (produzione intercettata e walker Elo; `max scarto` = massimo valore assoluto):

| Lega | Righe produzione | max |u25 intercettato − banco| | max |gg intercettato − banco| | max |Σ1X2 − 1| | Righe walker unite (1:1) | FTR walker ≠ gol | FTR quote ≠ gol |
|---|---|---|---|---|---|---|---|
| Serie A | 1570 | 0.00e+00 | 0.00e+00 | 1.59e-05 | 1570 | 0 | 0 |
| Premier League | 1570 | 0.00e+00 | 0.00e+00 | 1.93e-04 | 1570 | 0 | 0 |
| La Liga | 1589 | 0.00e+00 | 0.00e+00 | 5.63e-05 | 1589 | 0 | 0 |
| Bundesliga | 1260 | 0.00e+00 | 0.00e+00 | 1.60e-03 | 1260 | 0 | 0 |
| Ligue 1 | 1343 | 0.00e+00 | 0.00e+00 | 8.34e-05 | 1343 | 0 | 0 |

Scarto massimo blend: `|blend − (w·Poisson + (1−w)·Elo)|` = 0.00e+00 (dovrebbe essere 0 a precisione macchina: il blend e' quello di produzione).

## 1. Dati di mercato: copertura e de-vig

| Lega | Stagione | Righe | Con modello | B365H (non nulli) | B365CH (non nulli) | PSCH (non nulli) | Terna pre valida | Terna chiusura B365 valida | Terna Pinnacle chiusura valida |
|---|---|---|---|---|---|---|---|---|---|
| Serie A | 2022/23 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 |
| Serie A | 2023/24 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 |
| Serie A | 2024/25 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 |
| Serie A | 2025/26 | 380 | 380 | 380 | 380 | 198 | 380 | 380 | 198 |
| Serie A | 2026/27 | 50 | 50 | 0 | 0 | 0 | 0 | 0 | 0 |
| Premier League | 2022/23 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 |
| Premier League | 2023/24 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 |
| Premier League | 2024/25 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 |
| Premier League | 2025/26 | 380 | 380 | 380 | 380 | 210 | 380 | 380 | 210 |
| Premier League | 2026/27 | 50 | 50 | 0 | 0 | 0 | 0 | 0 | 0 |
| La Liga | 2022/23 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 |
| La Liga | 2023/24 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 |
| La Liga | 2024/25 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 |
| La Liga | 2025/26 | 380 | 380 | 380 | 380 | 188 | 380 | 380 | 188 |
| La Liga | 2026/27 | 69 | 69 | 0 | 0 | 0 | 0 | 0 | 0 |
| Bundesliga | 2022/23 | 306 | 306 | 306 | 306 | 306 | 306 | 306 | 306 |
| Bundesliga | 2023/24 | 306 | 306 | 306 | 306 | 306 | 306 | 306 | 306 |
| Bundesliga | 2024/25 | 306 | 306 | 306 | 306 | 306 | 306 | 306 | 306 |
| Bundesliga | 2025/26 | 306 | 306 | 306 | 306 | 149 | 306 | 306 | 149 |
| Bundesliga | 2026/27 | 36 | 36 | 0 | 0 | 0 | 0 | 0 | 0 |
| Ligue 1 | 2022/23 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 |
| Ligue 1 | 2023/24 | 306 | 306 | 306 | 306 | 306 | 306 | 306 | 306 |
| Ligue 1 | 2024/25 | 306 | 306 | 306 | 306 | 306 | 306 | 306 | 306 |
| Ligue 1 | 2025/26 | 306 | 306 | 306 | 306 | 153 | 306 | 306 | 153 |
| Ligue 1 | 2026/27 | 45 | 45 | 0 | 0 | 0 | 0 | 0 | 0 |

| Campione di valutazione (2024/25 + 2025/26) | Righe |
|---|---|
| Righe totali delle due stagioni | 3504 |
| Senza probabilita' del modello | 0 |
| Senza terna B365 pre-chiusura | 0 |
| Senza terna B365 chiusura | 0 |
| **Campione comune usato** (modello + B365 pre + B365 chiusura) | 3504 |
| di cui con quota Pinnacle di chiusura (campione Pinnacle) | 2650 |

La pre-chiusura e' quella dichiarata dalla commessa (B365H/D/A, raccolte il venerdi' o il martedi'). Il CSV non contiene l'orario di rilevazione: la dicitura e' dichiarata, non verificata dal file.

Sensibilita' de-vig: la decisione usa il proporzionale; lo Shin e' riportato in §2 (righe Shin).

## 2. Qualita' delle probabilita' per fonte

LogLoss, Brier (somma sui 3 esiti), RPS (esiti ordinati 1 < X < 2); BSS = 1 − punteggio/punteggio del base rate del train. Reliability/resolution per esito con 10 bin (`baserate_oos.decomp`). Valori piu' bassi = meglio; BSS e resolution piu' alti = meglio.

### 2a. Campione comune

| Fonte | Campione | n | LogLoss | Brier | RPS | BSS Brier | BSS LogLoss | BSS RPS | 1: rel / res | X: rel / res | 2: rel / res |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Modello blend (0,25 Poisson + 0,75 Elo) | comune n=3504 | 3504 | 0.9940 | 0.5919 | 0.2019 | 0.0913 | 0.0762 | 0.1272 | 0.0007 / 0.0323 | 0.0016 / 0.0018 | 0.0005 / 0.0260 |
| Poisson puro (testa 1X2 di produzione) | comune n=3504 | 3504 | 1.0089 | 0.6014 | 0.2068 | 0.0768 | 0.0623 | 0.1063 | 0.0033 / 0.0299 | 0.0012 / 0.0017 | 0.0038 / 0.0250 |
| Elo puro (walker, seeding S3) | comune n=3504 | 3504 | 0.9990 | 0.5945 | 0.2029 | 0.0874 | 0.0715 | 0.1232 | 0.0012 / 0.0313 | 0.0020 / 0.0013 | 0.0007 / 0.0255 |
| B365 pre-chiusura (de-vig prop.) | comune n=3504 | 3504 | 0.9719 | 0.5781 | 0.1962 | 0.1126 | 0.0967 | 0.1520 | 0.0006 / 0.0372 | 0.0000 / 0.0022 | 0.0006 / 0.0301 |
| B365 chiusura (de-vig prop.) | comune n=3504 | 3504 | 0.9700 | 0.5769 | 0.1957 | 0.1144 | 0.0985 | 0.1542 | 0.0006 / 0.0394 | 0.0000 / 0.0020 | 0.0006 / 0.0312 |
| B365 pre-chiusura (Shin) | comune n=3504 | 3504 | 0.9712 | 0.5777 | 0.1960 | 0.1132 | 0.0974 | 0.1528 | 0.0006 / 0.0385 | 0.0001 / 0.0023 | 0.0006 / 0.0299 |
| B365 chiusura (Shin) | comune n=3504 | 3504 | 0.9691 | 0.5765 | 0.1955 | 0.1150 | 0.0993 | 0.1550 | 0.0005 / 0.0395 | 0.0001 / 0.0021 | 0.0004 / 0.0313 |

### 2b. Campione con quota Pinnacle di chiusura

| Fonte | Campione | n | LogLoss | Brier | RPS | BSS Brier | BSS LogLoss | BSS RPS | 1: rel / res | X: rel / res | 2: rel / res |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Modello blend (0,25 Poisson + 0,75 Elo) | Pinnacle n=2650 | 2650 | 0.9876 | 0.5874 | 0.1998 | 0.0988 | 0.0823 | 0.1385 | 0.0006 / 0.0344 | 0.0016 / 0.0018 | 0.0007 / 0.0290 |
| B365 pre-chiusura (de-vig prop.) | Pinnacle n=2650 | 2650 | 0.9642 | 0.5731 | 0.1940 | 0.1207 | 0.1040 | 0.1633 | 0.0008 / 0.0397 | 0.0001 / 0.0025 | 0.0007 / 0.0329 |
| B365 chiusura (de-vig prop.) | Pinnacle n=2650 | 2650 | 0.9625 | 0.5720 | 0.1936 | 0.1224 | 0.1057 | 0.1651 | 0.0009 / 0.0417 | 0.0000 / 0.0023 | 0.0008 / 0.0339 |
| Pinnacle chiusura (de-vig prop.) | Pinnacle n=2650 | 2650 | 0.9618 | 0.5716 | 0.1935 | 0.1229 | 0.1063 | 0.1656 | 0.0007 / 0.0414 | 0.0001 / 0.0031 | 0.0006 / 0.0336 |
| Pinnacle chiusura (Shin) | Pinnacle n=2650 | 2650 | 0.9612 | 0.5714 | 0.1934 | 0.1233 | 0.1068 | 0.1661 | 0.0008 / 0.0416 | 0.0001 / 0.0029 | 0.0004 / 0.0334 |

### 2c. Combinazioni (campione comune, valutazione out-of-sample)

| Fonte | Campione | n | LogLoss | Brier | RPS | BSS Brier | BSS LogLoss | BSS RPS | 1: rel / res | X: rel / res | 2: rel / res |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Modello blend (0,25 Poisson + 0,75 Elo) | OOS (combinazioni) | 3504 | 0.9940 | 0.5919 | 0.2019 | 0.0913 | 0.0762 | 0.1272 | 0.0007 / 0.0323 | 0.0016 / 0.0018 | 0.0005 / 0.0260 |
| B365 pre-chiusura (de-vig prop.) | OOS (combinazioni) | 3504 | 0.9719 | 0.5781 | 0.1962 | 0.1126 | 0.0967 | 0.1520 | 0.0006 / 0.0372 | 0.0000 / 0.0022 | 0.0006 / 0.0301 |
| Combinazione (b): regressione condizionale | OOS (combinazioni) | 3504 | 0.9715 | 0.5779 | 0.1959 | 0.1129 | 0.0971 | 0.1534 | 0.0004 / 0.0390 | 0.0005 / 0.0024 | 0.0006 / 0.0308 |
| Combinazione (a): pool lineare | OOS (combinazioni) | 3504 | 0.9719 | 0.5781 | 0.1962 | 0.1126 | 0.0967 | 0.1520 | 0.0006 / 0.0372 | 0.0000 / 0.0022 | 0.0006 / 0.0301 |

## 2d. Differenze appaiate (A − B), bootstrap a blocchi, 2000 repliche, IC 95%

Delta negativo su LogLoss/Brier/RPS = A migliore di B. Delta positivo su resolution = A piu' informativa. Campione pooled = tutte le partite valutate; righe per lega = stesso calcolo sulla lega.

| Confronto | Campione | n | Δ LogLoss | Δ Brier | Δ RPS | Δ resolution per esito |
|---|---|---|---|---|---|---|
| pooled | mercato pre - modello | 3504 | -0.0221 [-0.0279; -0.0162] | -0.0139 [-0.0177; -0.0101] | -0.0057 [-0.0074; -0.0041] | 1: 0.0049 [0.0025; 0.0071] ; X: 0.0004 [-0.0006; 0.0015] ; 2: 0.0041 [0.0020; 0.0062] |
| Serie A | mercato pre - modello | 760 | -0.0264 [-0.0397; -0.0136] | -0.0160 [-0.0246; -0.0078] | -0.0063 [-0.0096; -0.0030] | 1: 0.0072 [0.0007; 0.0132] ; X: 0.0008 [-0.0016; 0.0042] ; 2: 0.0047 [-0.0017; 0.0104] |
| Premier League | mercato pre - modello | 760 | -0.0182 [-0.0298; -0.0066] | -0.0112 [-0.0187; -0.0038] | -0.0044 [-0.0078; -0.0013] | 1: 0.0061 [0.0000; 0.0113] ; X: 0.0002 [-0.0013; 0.0024] ; 2: 0.0004 [-0.0051; 0.0056] |
| La Liga | mercato pre - modello | 760 | -0.0180 [-0.0310; -0.0058] | -0.0127 [-0.0212; -0.0048] | -0.0058 [-0.0097; -0.0025] | 1: 0.0037 [-0.0028; 0.0096] ; X: -0.0003 [-0.0029; 0.0030] ; 2: 0.0050 [-0.0012; 0.0104] |
| Bundesliga | mercato pre - modello | 612 | -0.0300 [-0.0449; -0.0155] | -0.0178 [-0.0278; -0.0086] | -0.0069 [-0.0112; -0.0028] | 1: 0.0028 [-0.0048; 0.0092] ; X: 0.0006 [-0.0014; 0.0034] ; 2: 0.0088 [0.0021; 0.0147] |
| Ligue 1 | mercato pre - modello | 612 | -0.0188 [-0.0326; -0.0061] | -0.0122 [-0.0211; -0.0041] | -0.0053 [-0.0091; -0.0016] | 1: 0.0021 [-0.0046; 0.0074] ; X: 0.0003 [-0.0021; 0.0027] ; 2: 0.0044 [-0.0016; 0.0104] |
| pooled | mercato chiusura - modello | 3504 | -0.0240 [-0.0303; -0.0176] | -0.0151 [-0.0192; -0.0109] | -0.0062 [-0.0080; -0.0044] | 1: 0.0071 [0.0044; 0.0096] ; X: 0.0002 [-0.0007; 0.0013] ; 2: 0.0051 [0.0028; 0.0075] |
| Serie A | mercato chiusura - modello | 760 | -0.0287 [-0.0433; -0.0138] | -0.0167 [-0.0262; -0.0073] | -0.0064 [-0.0101; -0.0026] | 1: 0.0071 [0.0003; 0.0138] ; X: 0.0004 [-0.0021; 0.0033] ; 2: 0.0027 [-0.0043; 0.0086] |
| Premier League | mercato chiusura - modello | 760 | -0.0224 [-0.0353; -0.0104] | -0.0143 [-0.0224; -0.0065] | -0.0055 [-0.0092; -0.0020] | 1: 0.0074 [0.0012; 0.0122] ; X: 0.0006 [-0.0012; 0.0030] ; 2: 0.0025 [-0.0038; 0.0086] |
| La Liga | mercato chiusura - modello | 760 | -0.0207 [-0.0349; -0.0077] | -0.0144 [-0.0236; -0.0056] | -0.0069 [-0.0111; -0.0031] | 1: 0.0089 [0.0020; 0.0151] ; X: -0.0013 [-0.0035; 0.0016] ; 2: 0.0053 [-0.0014; 0.0115] |
| Bundesliga | mercato chiusura - modello | 612 | -0.0294 [-0.0455; -0.0133] | -0.0176 [-0.0283; -0.0068] | -0.0069 [-0.0115; -0.0022] | 1: 0.0042 [-0.0047; 0.0119] ; X: 0.0002 [-0.0019; 0.0034] ; 2: 0.0082 [0.0007; 0.0148] |
| Ligue 1 | mercato chiusura - modello | 612 | -0.0190 [-0.0339; -0.0050] | -0.0123 [-0.0218; -0.0034] | -0.0055 [-0.0096; -0.0016] | 1: 0.0062 [-0.0010; 0.0127] ; X: 0.0005 [-0.0020; 0.0029] ; 2: 0.0058 [-0.0005; 0.0116] |
| pooled | Pinnacle chiusura - modello | 2650 | -0.0258 [-0.0327; -0.0190] | -0.0157 [-0.0201; -0.0113] | -0.0063 [-0.0081; -0.0045] | 1: 0.0070 [0.0040; 0.0097] ; X: 0.0013 [0.0000; 0.0029] ; 2: 0.0046 [0.0021; 0.0073] |
| pooled | Pinnacle chiusura - B365 pre | 2650 | -0.0024 [-0.0051; 0.0004] | -0.0014 [-0.0032; 0.0004] | -0.0005 [-0.0013; 0.0003] | 1: 0.0017 [-0.0003; 0.0037] ; X: 0.0006 [-0.0005; 0.0017] ; 2: 0.0007 [-0.0010; 0.0024] |
| pooled | contesto: mercato pre - Poisson puro | 3504 | -0.0370 [-0.0462; -0.0275] | -0.0233 [-0.0292; -0.0172] | -0.0106 [-0.0132; -0.0077] | 1: 0.0073 [0.0044; 0.0098] ; X: 0.0004 [-0.0008; 0.0014] ; 2: 0.0051 [0.0025; 0.0076] |
| Serie A | contesto: mercato pre - Poisson puro | 760 | -0.0307 [-0.0495; -0.0121] | -0.0200 [-0.0322; -0.0074] | -0.0095 [-0.0151; -0.0041] | 1: 0.0061 [-0.0024; 0.0128] ; X: -0.0004 [-0.0043; 0.0030] ; 2: 0.0085 [0.0011; 0.0151] |
| Premier League | contesto: mercato pre - Poisson puro | 760 | -0.0284 [-0.0484; -0.0100] | -0.0192 [-0.0318; -0.0072] | -0.0083 [-0.0142; -0.0028] | 1: 0.0073 [0.0005; 0.0126] ; X: -0.0007 [-0.0040; 0.0018] ; 2: 0.0020 [-0.0050; 0.0081] |
| La Liga | contesto: mercato pre - Poisson puro | 760 | -0.0378 [-0.0604; -0.0180] | -0.0231 [-0.0370; -0.0108] | -0.0105 [-0.0171; -0.0047] | 1: 0.0069 [-0.0015; 0.0138] ; X: 0.0010 [-0.0023; 0.0040] ; 2: 0.0076 [0.0007; 0.0140] |
| Bundesliga | contesto: mercato pre - Poisson puro | 612 | -0.0439 [-0.0691; -0.0206] | -0.0256 [-0.0403; -0.0111] | -0.0108 [-0.0176; -0.0044] | 1: 0.0091 [0.0006; 0.0157] ; X: -0.0010 [-0.0058; 0.0026] ; 2: 0.0070 [-0.0003; 0.0138] |
| Ligue 1 | contesto: mercato pre - Poisson puro | 612 | -0.0476 [-0.0702; -0.0253] | -0.0307 [-0.0449; -0.0165] | -0.0145 [-0.0213; -0.0078] | 1: 0.0057 [-0.0027; 0.0121] ; X: 0.0004 [-0.0028; 0.0028] ; 2: 0.0044 [-0.0028; 0.0112] |
| pooled | contesto: mercato pre - Elo puro | 3504 | -0.0271 [-0.0335; -0.0206] | -0.0164 [-0.0203; -0.0125] | -0.0067 [-0.0084; -0.0049] | 1: 0.0059 [0.0033; 0.0083] ; X: 0.0009 [-0.0000; 0.0020] ; 2: 0.0047 [0.0024; 0.0069] |
| Serie A | contesto: mercato pre - Elo puro | 760 | -0.0348 [-0.0499; -0.0198] | -0.0200 [-0.0287; -0.0112] | -0.0075 [-0.0109; -0.0040] | 1: 0.0065 [-0.0001; 0.0128] ; X: 0.0011 [-0.0014; 0.0045] ; 2: 0.0048 [-0.0019; 0.0107] |
| Premier League | contesto: mercato pre - Elo puro | 760 | -0.0254 [-0.0382; -0.0123] | -0.0147 [-0.0227; -0.0068] | -0.0059 [-0.0096; -0.0024] | 1: 0.0066 [0.0001; 0.0124] ; X: 0.0004 [-0.0014; 0.0026] ; 2: 0.0031 [-0.0021; 0.0079] |
| La Liga | contesto: mercato pre - Elo puro | 760 | -0.0201 [-0.0337; -0.0073] | -0.0141 [-0.0228; -0.0059] | -0.0064 [-0.0102; -0.0030] | 1: 0.0050 [-0.0013; 0.0102] ; X: -0.0005 [-0.0030; 0.0027] ; 2: 0.0067 [0.0003; 0.0125] |
| Bundesliga | contesto: mercato pre - Elo puro | 612 | -0.0355 [-0.0514; -0.0196] | -0.0210 [-0.0308; -0.0110] | -0.0082 [-0.0124; -0.0042] | 1: 0.0070 [-0.0011; 0.0141] ; X: 0.0018 [-0.0004; 0.0047] ; 2: 0.0084 [0.0008; 0.0152] |
| Ligue 1 | contesto: mercato pre - Elo puro | 612 | -0.0200 [-0.0347; -0.0063] | -0.0125 [-0.0214; -0.0041] | -0.0051 [-0.0090; -0.0016] | 1: 0.0015 [-0.0057; 0.0076] ; X: 0.0005 [-0.0019; 0.0028] ; 2: 0.0022 [-0.0042; 0.0095] |
| pooled | chiusura - pre-chiusura (B365) | 3504 | -0.0019 [-0.0043; 0.0003] | -0.0012 [-0.0028; 0.0004] | -0.0005 [-0.0013; 0.0002] | 1: 0.0022 [0.0006; 0.0038] ; X: -0.0002 [-0.0009; 0.0005] ; 2: 0.0011 [-0.0005; 0.0026] |
| Serie A | chiusura - pre-chiusura (B365) | 760 | -0.0023 [-0.0073; 0.0028] | -0.0007 [-0.0040; 0.0026] | -0.0001 [-0.0015; 0.0014] | 1: -0.0001 [-0.0043; 0.0043] ; X: -0.0004 [-0.0031; 0.0017] ; 2: -0.0020 [-0.0060; 0.0017] |
| Premier League | chiusura - pre-chiusura (B365) | 760 | -0.0042 [-0.0093; 0.0012] | -0.0031 [-0.0065; 0.0004] | -0.0010 [-0.0026; 0.0006] | 1: 0.0013 [-0.0027; 0.0049] ; X: 0.0004 [-0.0014; 0.0023] ; 2: 0.0021 [-0.0016; 0.0056] |
| La Liga | chiusura - pre-chiusura (B365) | 760 | -0.0027 [-0.0076; 0.0026] | -0.0018 [-0.0051; 0.0019] | -0.0011 [-0.0026; 0.0006] | 1: 0.0052 [0.0007; 0.0098] ; X: -0.0011 [-0.0032; 0.0009] ; 2: 0.0003 [-0.0045; 0.0050] |
| Bundesliga | chiusura - pre-chiusura (B365) | 612 | 0.0006 [-0.0042; 0.0058] | 0.0003 [-0.0030; 0.0037] | 0.0000 [-0.0015; 0.0017] | 1: 0.0014 [-0.0037; 0.0068] ; X: -0.0004 [-0.0020; 0.0016] ; 2: -0.0006 [-0.0071; 0.0054] |
| Ligue 1 | chiusura - pre-chiusura (B365) | 612 | -0.0002 [-0.0069; 0.0062] | -0.0001 [-0.0045; 0.0043] | -0.0002 [-0.0023; 0.0018] | 1: 0.0041 [-0.0004; 0.0088] ; X: 0.0002 [-0.0015; 0.0018] ; 2: 0.0013 [-0.0045; 0.0071] |

## 3. Il modello aggiunge qualcosa al mercato?

Rolling-origin: il fold A stima su 2023/24 e valuta 2024/25; il fold B stima su 2023/24+2024/25 e valuta 2025/26. Combinazione (a): p = α·modello + (1−α)·mercato pre-chiusura, α per minimo LogLoss. Combinazione (b): regressione condizionale multinomiale su esiti 1/X/2 con log-probabilita' di modello e mercato: S_k = a_k + β_mod·log p_mod,k + β_mkt·log p_mkt,k (β condivisi fra esiti, a_X = 0). IC 95% da bootstrap a blocchi sul fold di stima.

| Fold | Stima su | Valuta | n stima / n valutazione | β modello [IC] | β mercato [IC] | α pool [IC] | Δ LogLoss (b) − mercato [IC] | Δ LogLoss (a) − mercato [IC] | Δ LogLoss (b) − mercato ricalibrato [IC] (controllo) |
|---|---|---|---|---|---|---|---|---|---|
| A | 2023/24 | 2024/25 | 1752 / 1752 | -0.3198 [-0.6337; -0.0168] | 1.6326 [1.3171; 1.9799] | 0.0000 [0.0000; 0.0000] | -0.0026 [-0.0083; 0.0036] | 0.0000 [0.0000; 0.0000] | -0.0023 [-0.0044; -0.0001] |
| B | 2023/24 + 2024/25 | 2025/26 | 3504 / 1752 | -0.4029 [-0.6289; -0.1890] | 1.6462 [1.4203; 1.8794] | 0.0000 [0.0000; 0.0000] | 0.0019 [-0.0033; 0.0069] | 0.0000 [-0.0000; 0.0000] | 0.0008 [-0.0023; 0.0038] |
| pooled OOS | A + B | 2024/25 + 2025/26 | - / 3504 | - | - | - | -0.0003 [-0.0043; 0.0036] | 0.0000 [0.0000; 0.0000] | -0.0007 [-0.0026; 0.0012] |

Controllo: il mercato ricalibrato usa la stessa stima del fold (β_mod = 0, β_mkt e intercette liberi). Se la combinazione (b) batte il mercato grezzo ma non quello ricalibrato, il guadagno viene dalla ricalibrazione del mercato e non dall'informazione del modello.


### Pesi della combinazione, errori standard (Hessiana) e IC bootstrap

| Fold | Parametro | Stima | SE (Hessiana) | Stima [IC 95% bootstrap] |
|---|---|---|---|---|
| A | peso_modello_b1 | -0.3198 | 0.1658 | -0.3198 [-0.6337; -0.0168] |
| A | peso_mercato_b2 | 1.6326 | 0.1730 | 1.6326 [1.3171; 1.9799] |
| A | a_casa | -0.2590 | 0.0826 | -0.2590 [-0.4159; -0.0886] |
| A | a_trasferta | -0.1545 | 0.0768 | -0.1545 [-0.3095; 0.0006] |
| A | alpha (pool lineare, peso modello) | 0.0000 | - | 0.0000 [0.0000; 0.0000] |
| B | peso_modello_b1 | -0.4029 | 0.1150 | -0.4029 [-0.6289; -0.1890] |
| B | peso_mercato_b2 | 1.6462 | 0.1231 | 1.6462 [1.4203; 1.8794] |
| B | a_casa | -0.1846 | 0.0579 | -0.1846 [-0.3011; -0.0739] |
| B | a_trasferta | -0.0247 | 0.0543 | -0.0247 [-0.1339; 0.0805] |
| B | alpha (pool lineare, peso modello) | 0.0000 | - | 0.0000 [0.0000; 0.0000] |

Lettura: β_mod = 0 (e β_mkt = 1, a = 0) coincide con il solo mercato grezzo. Un β_mod POSITIVO con IC che esclude lo zero indicherebbe informazione del modello non gia' nel mercato. Un β_mod NEGATIVO indica che, a parita' di mercato ricalibrato, il modello sposta le probabilita' nella direzione opposta a quella che l'esito conferma: non e' informazione aggiuntiva.


### Sensibilita' dei pesi (stesso protocollo, varianti di modello e di mercato)

| Variante | Fold | n stima | β modello [IC 95%] | β mercato [IC 95%] |
|---|---|---|---|---|
| blend + B365 pre prop. (decisione) | A | 1752 | -0.3198 [-0.6337; -0.0168] | 1.6326 [1.3171; 1.9799] |
| blend + B365 pre prop. (decisione) | B | 3504 | -0.4029 [-0.6289; -0.1890] | 1.6462 [1.4203; 1.8794] |
| blend + B365 pre Shin | A | 1752 | -0.3166 [-0.6319; -0.0031] | 1.5546 [1.2442; 1.8856] |
| blend + B365 pre Shin | B | 3504 | -0.4022 [-0.6160; -0.1915] | 1.5674 [1.3505; 1.7960] |
| Poisson puro + B365 pre prop. | A | 1752 | 0.0186 [-0.1823; 0.2267] | 1.3086 [1.0191; 1.6233] |
| Poisson puro + B365 pre prop. | B | 3504 | -0.0173 [-0.1546; 0.1192] | 1.2775 [1.0833; 1.4824] |
| Elo puro + B365 pre prop. | A | 1752 | -0.3894 [-0.7085; -0.0997] | 1.6641 [1.3861; 1.9816] |
| Elo puro + B365 pre prop. | B | 3504 | -0.4408 [-0.6399; -0.2453] | 1.6503 [1.4532; 1.8684] |
| blend + Pinnacle chiusura prop. (riferimento, non pre-chiusura) | A | 1752 | -0.1926 [-0.4980; 0.1189] | 1.4453 [1.1515; 1.7477] |
| blend + Pinnacle chiusura prop. (riferimento, non pre-chiusura) | B | 3504 | -0.3035 [-0.5048; -0.1014] | 1.4800 [1.2720; 1.6837] |

La variante con Pinnacle di chiusura usa una quota di chiusura (informazione piu' tardiva di quella pre-chiusura): e' un riferimento di sensibilita', non un'alternativa operativa.

## 4. Effetto sulle scelte (regola del Top Mix)

Regola: esito 1X2 piu' probabile, ammesso se la probabilita' e' ≥ 0,55 (soglia di produzione con Elo). La riga `modello + veto` applica anche il veto di produzione |P_poisson − P_elo| < 0,25 (sensibilita'; il veto non esiste per il mercato, che non ha Elo). Hit rate e confidence con IC bootstrap.

| Periodo | Fonte | Scelte (n) | % righe ammesse | Hit rate [IC] | Confidence media [IC] | Confidence − hit rate [IC] |
|---|---|---|---|---|---|---|
| pooled OOS | Modello blend | 1479 | 42.2% | 0.6261 [0.6016; 0.6504] | 0.6795 [0.6749; 0.6841] | 0.0534 [0.0306; 0.0776] |
| pooled OOS | Mercato B365 pre-chiusura (prop.) | 1302 | 37.2% | 0.6751 [0.6496; 0.7007] | 0.6563 [0.6523; 0.6604] | -0.0188 [-0.0441; 0.0064] |
| pooled OOS | Combinazione (b) | 1504 | 42.9% | 0.6636 [0.6385; 0.6875] | 0.6752 [0.6709; 0.6796] | 0.0117 [-0.0121; 0.0362] |
| pooled OOS | Combinazione (a) | 1302 | 37.2% | 0.6751 [0.6496; 0.7007] | 0.6563 [0.6523; 0.6604] | -0.0188 [-0.0441; 0.0064] |
| pooled OOS | Mercato B365 chiusura (contesto) | 1297 | 37.0% | 0.6762 [0.6510; 0.7021] | 0.6580 [0.6541; 0.6622] | -0.0182 [-0.0427; 0.0074] |
| pooled OOS | Modello + veto di produzione \|Poisson-Elo\|<0,25 (sensibilita') | 1445 | 41.2% | 0.6208 [0.5954; 0.6452] | 0.6808 [0.6761; 0.6854] | 0.0600 [0.0363; 0.0850] |
| 2024/25 | Modello blend | 764 | 43.6% | 0.6191 [0.5841; 0.6531] | 0.6792 [0.6727; 0.6860] | 0.0601 [0.0266; 0.0948] |
| 2024/25 | Mercato B365 pre-chiusura (prop.) | 689 | 39.3% | 0.6705 [0.6362; 0.7045] | 0.6581 [0.6526; 0.6635] | -0.0124 [-0.0454; 0.0212] |
| 2024/25 | Combinazione (b) | 799 | 45.6% | 0.6671 [0.6332; 0.6988] | 0.6813 [0.6752; 0.6871] | 0.0142 [-0.0179; 0.0469] |
| 2024/25 | Combinazione (a) | 689 | 39.3% | 0.6705 [0.6362; 0.7045] | 0.6581 [0.6526; 0.6635] | -0.0124 [-0.0454; 0.0212] |
| 2025/26 | Modello blend | 715 | 40.8% | 0.6336 [0.5970; 0.6697] | 0.6799 [0.6734; 0.6862] | 0.0463 [0.0109; 0.0821] |
| 2025/26 | Mercato B365 pre-chiusura (prop.) | 613 | 35.0% | 0.6803 [0.6431; 0.7176] | 0.6543 [0.6484; 0.6603] | -0.0260 [-0.0633; 0.0113] |
| 2025/26 | Combinazione (b) | 705 | 40.2% | 0.6596 [0.6246; 0.6961] | 0.6684 [0.6621; 0.6748] | 0.0088 [-0.0278; 0.0432] |
| 2025/26 | Combinazione (a) | 613 | 35.0% | 0.6803 [0.6431; 0.7176] | 0.6543 [0.6484; 0.6603] | -0.0260 [-0.0633; 0.0113] |

### 4b. Campione Pinnacle di chiusura

| Fonte | Scelte (n) | % righe ammesse | Hit rate [IC] | Confidence media [IC] | Confidence − hit rate [IC] |
|---|---|---|---|---|---|
| Modello blend | 1108 | 41.8% | 0.6318 [0.6043; 0.6603] | 0.6780 [0.6725; 0.6831] | 0.0462 [0.0180; 0.0720] |
| Mercato B365 pre-chiusura (prop.) | 992 | 37.4% | 0.6845 [0.6568; 0.7143] | 0.6584 [0.6537; 0.6630] | -0.0260 [-0.0551; 0.0021] |
| Pinnacle chiusura (de-vig prop.) | 1002 | 37.8% | 0.6896 [0.6611; 0.7185] | 0.6668 [0.6618; 0.6717] | -0.0228 [-0.0513; 0.0051] |

### 4c. Stessa N: le N scelte piu' sicure per ciascuna fonte (senza soglia), valutazione pooled

N scelto come minimo delle scelte Top Mix (modello, mercato pre, combinazione b): N = 1302 (conteggi: 1479 modello, 1302 mercato pre, 1504 combinazione b). Valori di N analizzati: [100, 200, 400, 1302].

| N | Fonte | Hit rate delle N piu' sicure [IC] | Confidence minima tra le N |
|---|---|---|---|
| 100 | Modello blend | 0.8400 [0.7613; 0.9140] | 0.8418 |
| 100 | Mercato B365 pre-chiusura (prop.) | 0.9100 [0.8469; 0.9626] | 0.7865 |
| 100 | Combinazione (b) | 0.9200 [0.8605; 0.9688] | 0.8302 |
| 200 | Modello blend | 0.8000 [0.7427; 0.8537] | 0.7971 |
| 200 | Mercato B365 pre-chiusura (prop.) | 0.8400 [0.7885; 0.8889] | 0.7470 |
| 200 | Combinazione (b) | 0.8600 [0.8093; 0.9046] | 0.7931 |
| 400 | Modello blend | 0.7750 [0.7335; 0.8133] | 0.7367 |
| 400 | Mercato B365 pre-chiusura (prop.) | 0.8050 [0.7638; 0.8411] | 0.6917 |
| 400 | Combinazione (b) | 0.8000 [0.7583; 0.8390] | 0.7344 |
| 1302 | Modello blend | 0.6452 [0.6183; 0.6712] | 0.5743 |
| 1302 | Mercato B365 pre-chiusura (prop.) | 0.6751 [0.6496; 0.7007] | 0.5502 |
| 1302 | Combinazione (b) | 0.6743 [0.6482; 0.6995] | 0.5740 |

### 4d. Sottoinsieme di consenso (modello e mercato pre-chiusura concordi, entrambi ≥ 0,55)

| Gruppo | n | Hit rate [IC] |
|---|---|---|
| Consenso: esito concordato (modello = mercato) | 1144 | 0.6818 [0.6555; 0.7077] |
| Resto: esito piu' probabile del modello, senza consenso | 2360 | 0.4449 [0.4256; 0.4645] |
| Differenza consenso − resto | - | 0.2369 [0.2051; 0.2692] |

Solo le scelte Top Mix del modello (confidence ≥ 0,55):

| Gruppo | n | Hit rate [IC] |
|---|---|---|
| Scelte del modello CON consenso di mercato | 1144 | 0.6818 [0.6555; 0.7077] |
| Scelte del modello SENZA consenso di mercato | 335 | 0.4358 [0.3821; 0.4909] |
| Differenza (con − senza) | - | 0.2460 [0.1828; 0.3056]; Fisher p = 0.0000 |

## 5. Regola di decisione (fissata prima dei numeri)

- **COMBINARE** se la combinazione (b) batte il mercato pre-chiusura con Δ LogLoss pooled < 0, IC 95% che esclude lo zero e segno negativo in entrambi i fold.
- **MERCATO** se il peso del modello nella combinazione (b) ha IC 95% che contiene lo zero in entrambi i fold.
- Altrimenti: **NESSUN VERDETTO AUTOMATICO** (segnalato, non forzato).

| Criterio | Combinazione (b) — decisione | Combinazione (a) — controllo |
|---|---|---|
| Δ LogLoss pooled OOS [IC 95%] | -0.0003 [-0.0043; 0.0036] | 0.0000 [0.0000; 0.0000] |
| Δ LogLoss fold A (2024/25) | -0.0026 | 0.0000 |
| Δ LogLoss fold B (2025/26) | 0.0019 | 0.0000 |
| Peso modello, IC fold A | [-0.6337; -0.0168] | [0.0000; 0.0000] |
| Peso modello, IC fold B | [-0.6289; -0.1890] | [0.0000; 0.0000] |
| **Verdetto** | **NESSUN VERDETTO AUTOMATICO** | **MERCATO** |

Nota: sulla combinazione (b) il peso del modello e' β (scala log, condiviso fra esiti); sulla (a) e' α (peso lineare). Il verdetto usa l'IC bootstrap del fold; il criterio 'segno in entrambi i fold' usa la stima puntuale.

**Motivi per cui i verdetti non scattano (generati dai numeri):**

- (b) COMBINARE non soddisfatto: Δ LogLoss pooled = -0.0003 [-0.0043; 0.0036] (IC include lo zero)
- (b) COMBINARE non soddisfatto: segni dei fold = A -0.0026, B +0.0019 (non entrambi negativi)
- (b) MERCATO non applicabile sul fold A: peso del modello distinguibile da zero (negativo; IC [-0.6337; -0.0168])
- (b) MERCATO non applicabile sul fold B: peso del modello distinguibile da zero (negativo; IC [-0.6289; -0.1890])
- (a) COMBINARE non soddisfatto: Δ LogLoss pooled = 0.0000 [0.0000; 0.0000] (IC degenere a 0)
- (a) COMBINARE non soddisfatto: segni dei fold = A +0.0000, B +0.0000 (non entrambi negativi)

Caso non coperto dalla regola: il peso del modello nella combinazione (b) e' significativamente NEGATIVO nei fold in cui il verdetto MERCATO non scatta. La regola prevede MERCATO solo per peso non distinguibile da zero; il caso e' segnalato, non risolto dal codice. Il criterio COMBINARE e' comunque non soddisfatto (vedi sopra).


Nota numerica: i confronti con zero usano la tolleranza 1e-06 (α̂ dell'ottimizzatore sul bordo 0 vale ~1e-8, non esattamente 0). Con il confronto esatto la combinazione (a) risultava 'nessun verdetto' per rumore di precisione; la tolleranza non cambia i numeri, solo il trattamento degli IC degeneri.

## 6. Limiti dichiarati

- La pre-chiusura B365 e' quella della commessa; l'orario di rilevazione non e' nel CSV.
- Il Poisson di produzione e' ricostruito con `production_totali` (archivio xG a cutoff); la parita' con il banco su u25/gg e' verificata riga per riga, non per l'app in esecuzione.
- Il veto di produzione e' riportato come sensibilita', non come regola principale (la regola della commessa non lo include).
- Il campione Pinnacle e' un sottoinsieme (chiusura Pinnacle mancante su parte delle partite 2025/26): i confronti con Pinnacle non sono sullo stesso campione del pooled.
- Il bootstrap a blocchi tratta le giornate come unita'; le giornate di una stessa lega condividono squadre e quindi non sono indipendenti oltre il blocco.

