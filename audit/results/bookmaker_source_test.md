# Quale bookmaker basta? — referto di audit (sola lettura)

Generato da `audit/bookmaker_source_test.py` (nessuna modifica a `SoccerMath/`). Base: `d7666f83c299203bf03cfecb96f4257f5372ebd7` su branch `arena/edb67158-soccermath2-0`. Bootstrap: 2000 repliche a blocchi (lega × stagione × giornata), seme 20261008. Tempo: 40.4 s. Comando: `python audit/bookmaker_source_test.py`.

Protocollo: identico alla PR #49 (`audit/onex2_market_test.py`), di cui si riusano de-vig, metriche, base rate del train, regola Top Mix (>= 0,55) e bootstrap a blocchi. Stagioni valutate: 2024/25 e 2025/26.

## 1. Copertura delle colonne (righe con terna valida)

| Lega | Stagione | Righe | B365 | Avg | Max | PS | CONS | BFD | BMGM | BV | BW | CL | LB | B365_shin | Avg_shin | PS_shin | CONS_shin | B365C | PSC | BFE |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Serie A | 2024/25 | 380 | 380 | 380 | 380 | 380 | 239 | 0 | 0 | 0 | 239 | 0 | 0 | 380 | 380 | 380 | 239 | 380 | 380 | 380 |
| Serie A | 2025/26 | 380 | 380 | 380 | 380 | 200 | 379 | 379 | 378 | 378 | 380 | 269 | 281 | 380 | 380 | 200 | 379 | 380 | 198 | 360 |
| Premier League | 2024/25 | 380 | 380 | 380 | 380 | 380 | 239 | 0 | 0 | 0 | 239 | 0 | 0 | 380 | 380 | 380 | 239 | 380 | 380 | 380 |
| Premier League | 2025/26 | 380 | 380 | 380 | 380 | 210 | 379 | 379 | 378 | 378 | 380 | 282 | 286 | 380 | 380 | 210 | 379 | 380 | 210 | 360 |
| La Liga | 2024/25 | 380 | 380 | 380 | 380 | 380 | 230 | 0 | 0 | 0 | 230 | 0 | 0 | 380 | 380 | 380 | 230 | 380 | 380 | 380 |
| La Liga | 2025/26 | 380 | 380 | 380 | 380 | 189 | 379 | 379 | 378 | 378 | 379 | 282 | 291 | 380 | 380 | 189 | 379 | 380 | 188 | 350 |
| Bundesliga | 2024/25 | 306 | 306 | 306 | 306 | 306 | 189 | 0 | 0 | 0 | 189 | 0 | 0 | 306 | 306 | 306 | 189 | 306 | 306 | 306 |
| Bundesliga | 2025/26 | 306 | 306 | 306 | 306 | 150 | 304 | 304 | 303 | 303 | 306 | 226 | 227 | 306 | 306 | 150 | 304 | 306 | 149 | 288 |
| Ligue 1 | 2024/25 | 306 | 306 | 306 | 306 | 306 | 189 | 0 | 0 | 0 | 189 | 0 | 0 | 306 | 306 | 306 | 189 | 306 | 306 | 306 |
| Ligue 1 | 2025/26 | 306 | 306 | 306 | 306 | 153 | 306 | 306 | 305 | 305 | 306 | 221 | 224 | 306 | 306 | 153 | 306 | 306 | 153 | 287 |

| Campione | Righe |
|---|---|
| comune (B365+Avg+Max validi) | 3504 |
| di cui con Pinnacle pre valido | 2654 |
| righe totali delle due stagioni | 3504 |

## 2. Qualita' delle probabilita' (campione comune)

LogLoss / Brier / RPS piu' bassi = meglio; BSS e resolution piu' alti = meglio. Reliability/resolution per esito con 10 bin, base rate del train come PR #34.

| Fonte | n | LogLoss | Brier | RPS | BSS Brier | BSS LogLoss | BSS RPS | rel/res per esito |
|---|---|---|---|---|---|---|---|---|
| Bet365 pre-chiusura (de-vig prop.) — RIFERIMENTO | 3504 | 0.9719 | 0.5781 | 0.1962 | 0.1126 | 0.0967 | 0.1520 | 1: 0.0006/0.0372 ; X: 0.0000/0.0022 ; 2: 0.0006/0.0301 |
| Media di mercato Avg (de-vig prop.) | 3504 | 0.9712 | 0.5778 | 0.1961 | 0.1130 | 0.0974 | 0.1524 | 1: 0.0006/0.0376 ; X: 0.0001/0.0024 ; 2: 0.0006/0.0308 |
| Massimo di mercato Max (de-vig prop.) | 3504 | 0.9705 | 0.5775 | 0.1960 | 0.1134 | 0.0980 | 0.1529 | 1: 0.0004/0.0376 ; X: 0.0001/0.0022 ; 2: 0.0005/0.0305 |
| Pinnacle (de-vig prop.) | 2654 | 0.9634 | 0.5728 | 0.1938 | 0.1214 | 0.1050 | 0.1642 | 1: 0.0009/0.0405 ; X: 0.0002/0.0029 ; 2: 0.0008/0.0338 |
| Consenso: media delle prob. de-vigate dei singoli book | 2833 | 0.9725 | 0.5787 | 0.1956 | 0.1093 | 0.0944 | 0.1484 | 1: 0.0007/0.0368 ; X: 0.0001/0.0020 ; 2: 0.0005/0.0298 |
| Betfred (de-vig prop.) | 1747 | 0.9781 | 0.5824 | 0.1977 | 0.1015 | 0.0875 | 0.1369 | 1: 0.0007/0.0352 ; X: 0.0001/0.0016 ; 2: 0.0006/0.0271 |
| BetMGM (de-vig prop.) | 1742 | 0.9772 | 0.5819 | 0.1976 | 0.1021 | 0.0882 | 0.1378 | 1: 0.0013/0.0357 ; X: 0.0001/0.0019 ; 2: 0.0004/0.0274 |
| BetVictor (de-vig prop.) | 1742 | 0.9780 | 0.5823 | 0.1978 | 0.1015 | 0.0875 | 0.1367 | 1: 0.0014/0.0351 ; X: 0.0002/0.0018 ; 2: 0.0004/0.0268 |
| Bet&Win / bwin (de-vig prop.) | 2837 | 0.9739 | 0.5796 | 0.1959 | 0.1080 | 0.0932 | 0.1466 | 1: 0.0006/0.0364 ; X: 0.0002/0.0022 ; 2: 0.0006/0.0295 |
| Coral (de-vig prop.) | 1280 | 0.9727 | 0.5790 | 0.1950 | 0.1046 | 0.0910 | 0.1423 | 1: 0.0015/0.0371 ; X: 0.0005/0.0023 ; 2: 0.0017/0.0302 |
| Ladbrokes (de-vig prop.) | 1309 | 0.9766 | 0.5818 | 0.1963 | 0.1011 | 0.0879 | 0.1379 | 1: 0.0018/0.0362 ; X: 0.0001/0.0017 ; 2: 0.0014/0.0288 |
| Bet365 pre-chiusura (de-vig Shin) | 3504 | 0.9712 | 0.5777 | 0.1960 | 0.1132 | 0.0974 | 0.1528 | 1: 0.0006/0.0385 ; X: 0.0001/0.0023 ; 2: 0.0006/0.0299 |
| Media di mercato Avg (de-vig Shin) | 3504 | 0.9705 | 0.5775 | 0.1960 | 0.1135 | 0.0980 | 0.1531 | 1: 0.0006/0.0381 ; X: 0.0001/0.0026 ; 2: 0.0006/0.0304 |
| Pinnacle (de-vig Shin) | 2654 | 0.9628 | 0.5725 | 0.1937 | 0.1218 | 0.1056 | 0.1648 | 1: 0.0009/0.0409 ; X: 0.0001/0.0027 ; 2: 0.0007/0.0335 |
| Consenso (de-vig Shin) | 2833 | 0.9718 | 0.5784 | 0.1954 | 0.1098 | 0.0951 | 0.1492 | 1: 0.0004/0.0373 ; X: 0.0002/0.0021 ; 2: 0.0003/0.0293 |
| Bet365 chiusura (contesto, de-vig prop.) | 3504 | 0.9700 | 0.5769 | 0.1957 | 0.1144 | 0.0985 | 0.1542 | 1: 0.0006/0.0394 ; X: 0.0000/0.0020 ; 2: 0.0006/0.0312 |
| Pinnacle chiusura (contesto, de-vig prop.) | 2650 | 0.9618 | 0.5716 | 0.1935 | 0.1229 | 0.1063 | 0.1656 | 1: 0.0007/0.0414 ; X: 0.0001/0.0031 ; 2: 0.0006/0.0336 |
| Betfair Exchange (senza commissione, de-vig prop.) | 3397 | 0.9701 | 0.5771 | 0.1961 | 0.1141 | 0.0983 | 0.1533 | 1: 0.0005/0.0382 ; X: 0.0000/0.0026 ; 2: 0.0005/0.0299 |

### 2b. Campione Pinnacle (dove la terna PS pre-chiusura e' valida)

| Fonte | n | LogLoss | Brier | RPS | BSS LogLoss |
|---|---|---|---|---|---|
| Bet365 pre-chiusura (de-vig prop.) — RIFERIMENTO | 2654 | 0.9644 | 0.5732 | 0.1940 | 0.1041 |
| Media di mercato Avg (de-vig prop.) | 2654 | 0.9637 | 0.5730 | 0.1939 | 0.1048 |
| Massimo di mercato Max (de-vig prop.) | 2654 | 0.9628 | 0.5726 | 0.1937 | 0.1056 |
| Pinnacle (de-vig prop.) | 2654 | 0.9634 | 0.5728 | 0.1938 | 0.1050 |
| Consenso: media delle prob. de-vigate dei singoli book | 1988 | 0.9630 | 0.5726 | 0.1923 | 0.1033 |
| Betfred (de-vig prop.) | 902 | 0.9621 | 0.5722 | 0.1925 | 0.1008 |
| BetMGM (de-vig prop.) | 902 | 0.9622 | 0.5723 | 0.1924 | 0.1007 |
| BetVictor (de-vig prop.) | 902 | 0.9629 | 0.5727 | 0.1927 | 0.1000 |
| Bet&Win / bwin (de-vig prop.) | 1987 | 0.9645 | 0.5735 | 0.1927 | 0.1018 |
| Coral (de-vig prop.) | 902 | 0.9641 | 0.5731 | 0.1929 | 0.0989 |
| Ladbrokes (de-vig prop.) | 902 | 0.9644 | 0.5733 | 0.1929 | 0.0986 |
| Bet365 pre-chiusura (de-vig Shin) | 2654 | 0.9633 | 0.5727 | 0.1937 | 0.1051 |
| Media di mercato Avg (de-vig Shin) | 2654 | 0.9627 | 0.5725 | 0.1937 | 0.1057 |
| Pinnacle (de-vig Shin) | 2654 | 0.9628 | 0.5725 | 0.1937 | 0.1056 |
| Consenso (de-vig Shin) | 1988 | 0.9618 | 0.5721 | 0.1920 | 0.1044 |
| Bet365 chiusura (contesto, de-vig prop.) | 2654 | 0.9626 | 0.5721 | 0.1936 | 0.1058 |
| Pinnacle chiusura (contesto, de-vig prop.) | 2650 | 0.9618 | 0.5716 | 0.1935 | 0.1063 |
| Betfair Exchange (senza commissione, de-vig prop.) | 2654 | 0.9628 | 0.5725 | 0.1937 | 0.1056 |

## 3. Scelte Top Mix (esito piu' probabile se >= 0,55)

| Fonte | Scelte | % righe ammesse | Hit rate [IC] | Confidence media [IC] | Confidence − hit rate [IC] |
|---|---|---|---|---|---|
| Bet365 pre-chiusura (de-vig prop.) — RIFERIMENTO | 1302 | 37.2% | 0.6751 [0.6496; 0.7004] | 0.6563 [0.6524; 0.6604] | -0.0188 [-0.0441; 0.0060] |
| Media di mercato Avg (de-vig prop.) | 1298 | 37.0% | 0.6780 [0.6518; 0.7040] | 0.6581 [0.6539; 0.6621] | -0.0199 [-0.0451; 0.0059] |
| Massimo di mercato Max (de-vig prop.) | 1342 | 38.3% | 0.6714 [0.6454; 0.6963] | 0.6629 [0.6587; 0.6671] | -0.0085 [-0.0334; 0.0169] |
| Pinnacle (de-vig prop.) | 1019 | 38.4% | 0.6850 [0.6569; 0.7132] | 0.6620 [0.6572; 0.6666] | -0.0230 [-0.0508; 0.0045] |
| Consenso: media delle prob. de-vigate dei singoli book | 1040 | 36.7% | 0.6779 [0.6486; 0.7082] | 0.6552 [0.6508; 0.6598] | -0.0227 [-0.0523; 0.0061] |
| Betfred (de-vig prop.) | 606 | 34.7% | 0.6766 [0.6391; 0.7134] | 0.6565 [0.6507; 0.6625] | -0.0201 [-0.0555; 0.0175] |
| BetMGM (de-vig prop.) | 627 | 36.0% | 0.6715 [0.6335; 0.7101] | 0.6582 [0.6529; 0.6641] | -0.0133 [-0.0501; 0.0240] |
| BetVictor (de-vig prop.) | 604 | 34.7% | 0.6887 [0.6507; 0.7257] | 0.6556 [0.6496; 0.6615] | -0.0332 [-0.0690; 0.0045] |
| Bet&Win / bwin (de-vig prop.) | 1005 | 35.4% | 0.6836 [0.6549; 0.7115] | 0.6547 [0.6500; 0.6596] | -0.0289 [-0.0554; -0.0013] |
| Coral (de-vig prop.) | 422 | 33.0% | 0.6991 [0.6540; 0.7426] | 0.6557 [0.6487; 0.6629] | -0.0434 [-0.0854; 0.0021] |
| Ladbrokes (de-vig prop.) | 437 | 33.4% | 0.6911 [0.6460; 0.7353] | 0.6532 [0.6462; 0.6603] | -0.0379 [-0.0818; 0.0056] |
| Bet365 pre-chiusura (de-vig Shin) | 1407 | 40.2% | 0.6645 [0.6399; 0.6893] | 0.6612 [0.6572; 0.6654] | -0.0033 [-0.0279; 0.0216] |
| Media di mercato Avg (de-vig Shin) | 1376 | 39.3% | 0.6708 [0.6465; 0.6970] | 0.6647 [0.6606; 0.6689] | -0.0061 [-0.0317; 0.0177] |
| Pinnacle (de-vig Shin) | 1055 | 39.8% | 0.6787 [0.6500; 0.7065] | 0.6674 [0.6626; 0.6722] | -0.0112 [-0.0391; 0.0168] |
| Consenso (de-vig Shin) | 1102 | 38.9% | 0.6724 [0.6466; 0.7004] | 0.6618 [0.6569; 0.6668] | -0.0106 [-0.0378; 0.0155] |
| Bet365 chiusura (contesto, de-vig prop.) | 1297 | 37.0% | 0.6762 [0.6504; 0.7022] | 0.6580 [0.6538; 0.6621] | -0.0182 [-0.0436; 0.0071] |
| Pinnacle chiusura (contesto, de-vig prop.) | 1002 | 37.8% | 0.6896 [0.6610; 0.7168] | 0.6668 [0.6619; 0.6719] | -0.0228 [-0.0498; 0.0052] |
| Betfair Exchange (senza commissione, de-vig prop.) | 1337 | 39.4% | 0.6687 [0.6424; 0.6924] | 0.6647 [0.6605; 0.6690] | -0.0039 [-0.0271; 0.0215] |

## 4. Differenze appaiate contro Bet365 (A − B365), IC 95% bootstrap

Delta negativo su LogLoss/Brier/RPS = A migliore di B365. L'hit rate e' appaiato sulle partite ammesse da ENTRAMBE le fonti.

| Fonte (A) | Δ LogLoss | Δ Brier | Δ RPS | Δ hit rate appaiato (n) |
|---|---|---|---|---|
| Media di mercato Avg (de-vig prop.) | -0.0007 [-0.0014; -0.0000] | -0.0002 [-0.0006; 0.0001] | -0.0001 [-0.0002; 0.0001] | +0.0000 [+0.0000; +0.0000] (n=1278) |
| Massimo di mercato Max (de-vig prop.) | -0.0014 [-0.0023; -0.0005] | -0.0005 [-0.0010; 0.0000] | -0.0002 [-0.0004; 0.0000] | +0.0000 [+0.0000; +0.0000] (n=1287) |
| Pinnacle (de-vig prop.) | -0.0009 [-0.0019; -0.0000] | -0.0004 [-0.0009; 0.0002] | -0.0002 [-0.0004; 0.0000] | +0.0000 [+0.0000; +0.0000] (n=984) |
| Consenso: media delle prob. de-vigate dei singoli book | -0.0003 [-0.0010; 0.0004] | -0.0001 [-0.0005; 0.0003] | -0.0000 [-0.0002; 0.0001] | +0.0000 [+0.0000; +0.0000] (n=1022) |
| Betfred (de-vig prop.) | -0.0009 [-0.0024; 0.0005] | -0.0004 [-0.0011; 0.0004] | -0.0001 [-0.0005; 0.0002] | +0.0000 [+0.0000; +0.0000] (n=592) |
| BetMGM (de-vig prop.) | -0.0013 [-0.0029; 0.0004] | -0.0005 [-0.0014; 0.0006] | -0.0002 [-0.0006; 0.0002] | +0.0000 [+0.0000; +0.0000] (n=596) |
| BetVictor (de-vig prop.) | -0.0005 [-0.0018; 0.0009] | -0.0000 [-0.0007; 0.0007] | 0.0000 [-0.0002; 0.0003] | +0.0000 [+0.0000; +0.0000] (n=594) |
| Bet&Win / bwin (de-vig prop.) | 0.0009 [-0.0002; 0.0020] | 0.0006 [0.0000; 0.0013] | 0.0003 [0.0001; 0.0006] | +0.0000 [+0.0000; +0.0000] (n=990) |
| Coral (de-vig prop.) | 0.0002 [-0.0014; 0.0018] | 0.0001 [-0.0008; 0.0011] | 0.0001 [-0.0003; 0.0005] | +0.0000 [+0.0000; +0.0000] (n=416) |
| Ladbrokes (de-vig prop.) | 0.0003 [-0.0014; 0.0020] | 0.0002 [-0.0007; 0.0012] | 0.0001 [-0.0003; 0.0005] | +0.0000 [+0.0000; +0.0000] (n=430) |
| Bet365 pre-chiusura (de-vig Shin) | -0.0007 [-0.0014; 0.0000] | -0.0003 [-0.0008; 0.0001] | -0.0002 [-0.0004; 0.0000] | +0.0000 [+0.0000; +0.0000] (n=1302) |
| Media di mercato Avg (de-vig Shin) | -0.0013 [-0.0023; -0.0003] | -0.0005 [-0.0011; 0.0000] | -0.0002 [-0.0005; -0.0000] | +0.0000 [+0.0000; +0.0000] (n=1300) |
| Pinnacle (de-vig Shin) | -0.0016 [-0.0028; -0.0003] | -0.0007 [-0.0014; 0.0001] | -0.0003 [-0.0006; -0.0000] | +0.0000 [+0.0000; +0.0000] (n=988) |
| Consenso (de-vig Shin) | -0.0010 [-0.0020; -0.0000] | -0.0004 [-0.0010; 0.0002] | -0.0002 [-0.0004; 0.0000] | +0.0000 [+0.0000; +0.0000] (n=1039) |
| Bet365 chiusura (contesto, de-vig prop.) | -0.0019 [-0.0043; 0.0006] | -0.0012 [-0.0028; 0.0005] | -0.0005 [-0.0012; 0.0003] | +0.0000 [+0.0000; +0.0000] (n=1197) |
| Pinnacle chiusura (contesto, de-vig prop.) | -0.0024 [-0.0053; 0.0004] | -0.0014 [-0.0033; 0.0005] | -0.0005 [-0.0014; 0.0004] | +0.0000 [+0.0000; +0.0000] (n=917) |
| Betfair Exchange (senza commissione, de-vig prop.) | -0.0013 [-0.0024; -0.0003] | -0.0005 [-0.0011; 0.0001] | -0.0002 [-0.0005; 0.0000] | +0.0000 [+0.0000; +0.0000] (n=1264) |

## 5. Verdetti (regola fissata prima dei numeri: C1 e C2 e C3)

C1 = Δ LogLoss non significativamente peggiore; C2 = Δ hit rate appaiato non peggiore; C3 = scarto di calibrazione con IC che contiene lo zero.

| Fonte | Esito | C1 | C2 | C3 |
|---|---|---|---|---|
| Media di mercato Avg (de-vig prop.) | EQUIVALENTE | sì | sì | sì |
| Massimo di mercato Max (de-vig prop.) | EQUIVALENTE | sì | sì | sì |
| Pinnacle (de-vig prop.) | EQUIVALENTE | sì | sì | sì |
| Consenso: media delle prob. de-vigate dei singoli book | EQUIVALENTE | sì | sì | sì |
| Betfred (de-vig prop.) | EQUIVALENTE | sì | sì | sì |
| BetMGM (de-vig prop.) | EQUIVALENTE | sì | sì | sì |
| BetVictor (de-vig prop.) | EQUIVALENTE | sì | sì | sì |
| Bet&Win / bwin (de-vig prop.) | NON EQUIVALENTE | sì | sì | NO |
| Coral (de-vig prop.) | EQUIVALENTE | sì | sì | sì |
| Ladbrokes (de-vig prop.) | EQUIVALENTE | sì | sì | sì |
| Bet365 pre-chiusura (de-vig Shin) | EQUIVALENTE | sì | sì | sì |
| Media di mercato Avg (de-vig Shin) | EQUIVALENTE | sì | sì | sì |
| Pinnacle (de-vig Shin) | EQUIVALENTE | sì | sì | sì |
| Consenso (de-vig Shin) | EQUIVALENTE | sì | sì | sì |
| Bet365 chiusura (contesto, de-vig prop.) | EQUIVALENTE | sì | sì | sì |
| Pinnacle chiusura (contesto, de-vig prop.) | EQUIVALENTE | sì | sì | sì |
| Betfair Exchange (senza commissione, de-vig prop.) | EQUIVALENTE | sì | sì | sì |

**Motivi per cui i verdetti non scattano (generati dai numeri):**

- C3 non soddisfatto: scarto di calibrazione -0.0289 IC [-0.0554; -0.0013] (non contiene lo zero)

## 6. Disponibilita' dei book dei CSV nella fonte dal vivo candidata

Bookmaker misurati da The Odds API (regioni eu,uk, snapshot 2026-10-08T23:11:02Z) sulle 5 leghe: 41. La colonna 'disponibile live' dice se lo stesso book e' tornato nelle risposte reali.

| Colonna CSV | Bookmaker | Disponibile live (misurato) | Chiavi API trovate |
|---|---|---|---|
| B365 | Bet365 pre-chiusura (de-vig prop.) — RIFERIMENTO | NO | — |
| BFD | Betfred (de-vig prop.) | sì | betfred_uk |
| BMGM | BetMGM (de-vig prop.) | NO | — |
| BV | BetVictor (de-vig prop.) | sì | betvictor |
| BW | Bet&Win / bwin (de-vig prop.) | NO | — |
| CL | Coral (de-vig prop.) | sì | coral |
| LB | Ladbrokes (de-vig prop.) | sì | ladbrokes_uk |
| PS | Pinnacle (de-vig prop.) | sì | pinnacle |
| BFE | Betfair Exchange (senza commissione, de-vig prop.) | sì | betfair_ex_eu, betfair_ex_uk |

## 7. Limiti dichiarati

- Le colonne pre-chiusura sono quelle dichiarate dalla commessa: il CSV non contiene l'orario di rilevazione della quota.
- Avg e Max sono aggregati di mercato calcolati dalla fonte (Betbrain/Oddsportal): la composizione del paniere non e' nel CSV e puo' cambiare nel tempo.
- Il de-vig proporzionale e' la decisione (come PR #49); lo Shin e' sensibilita'. Sulle quote dello scambio (BFE) il de-vig non tiene conto della commissione.
- Il campione Pinnacle e' un sottoinsieme (PS pre mancante su parte delle partite 2025/26): i valori non sono confrontabili riga per riga con il campione comune.
- Il bootstrap a blocchi tratta le giornate come unita'; giornate della stessa lega condividono le squadre e non sono indipendenti oltre il blocco.
- La disponibilita' live dei book e' MISURATA su uno snapshot del probe (The Odds API, regioni eu e uk): puo' cambiare senza preavviso.
