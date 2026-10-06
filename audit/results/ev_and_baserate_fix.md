# EV economico e benchmark base-rate OOS — referto PR #34

Esecuzione 2026-10-06, clone completo. Nessun file in `SoccerMath/` modificato.

## Riepilogo

- Il ROI pooled di tutti i modelli resta compreso fra circa **−12% e −16%** prima e dopo la correzione EV: la soglia economica corregge l'esecuzione, ma non rende profittevoli i modelli.
- I Totali sono **pari** al base rate train ed expanding con shrinkage: O/U 2.5 è pari; GG/NG è pari in Brier e peggiore in LogLoss contro il train.
- I Totali non mostrano capacità discriminante dimostrata oltre il base rate nei confronti pooled con IC.

## Evidenze

| Esito | Comando | Evidenza |
|---|---|---|
| OK | `git fetch --unshallow origin; git merge --ff-only origin/main` | fast-forward iniziale `af4924d..4e556ec`; HEAD iniziale `4e556ec2afe8f4fc818151c43f30baf6ab8c0882`; clone `false` a `--is-shallow-repository`; diff iniziale vuoto |
| OK | venv pulito + requirements | installazione exit 0 da `SoccerMath/requirements.txt`, `requirements-audit.txt`, `pytest` |
| OK | `.venv/bin/pytest -q audit/test_gg_ng_calibration.py audit/test_diagnose_clv_pinnacle.py audit/test_grid_search_ensemble_weight.py audit/test_economic_ev.py` | `65 passed in 7.83s` |
| OK | `.venv/bin/python audit/recalculate_ev.py` | `new_rows_not_old 0`; risultati pooled e bootstrap prodotti |
| OK | `.venv/bin/python audit/baserate_oos.py --reps 2000` | 3.504 osservazioni per mercato; output cella e pooled prodotti |

## 1. Inventario completo degli audit economici

“Helper sì” significa che la selezione economica corrente passa direttamente da `economic_ev.select_positive_ev`; i wrapper importati sono indicati.

| Script | Funzione/riga corrente | Conclusione prodotta e report | Helper | Rilancio |
|---|---|---|---|---|
| `analyze.py` | `simulate_roi_1x2:30`, `simulate_roi_ou:78` | tabelle ROI Serie A, `calibration_results.txt`, `ou_gg_calibration_results.txt` | sì | coperto dal replay equivalente `analyze_all`; non rilanciato separatamente |
| `analyze_all.py` | `simulate_roi_1x2:49`, `simulate_roi_ou:99` | ROI 5 leghe; `all_leagues_tables.txt`, `elo_fix_comparison.txt`, `dixon_coles_comparison.txt` | sì | exit 0 in 195 s, senza limite; log `output/analyze_all_full.log`. Le quantità economiche cambiano: per la prima cella, ad esempio, Poisson passa da 380 bet/ROI −17,41% a 326 bet/ROI −16,52%; lo script non codifica un verdetto qualitativo |
| `calibration_check.py` | importa `simulate_roi_1x2` | confronto calibrato/non calibrato, `calibration_results.txt` | sì, via wrapper | non richiesto separatamente dal wrapper |
| `draw_correction.py` | importa `simulate_roi_1x2` | confronto correzione pareggio, `draw_correction_results.txt` | sì, via wrapper | non richiesto separatamente dal wrapper |
| `premier_deep_dive.py` | `collect_bets:28`; importa wrapper ROI | ROI/IC Dixon-Coles, `premier_league_deep_dive.txt` | sì | exit 0 |
| `diagnose_production_baseline.py` | `roi_1x2:328`, `roi_ou:354` | baseline produzione, `results/production_baseline_comparison.md` | sì | exit 0; report rigenerato |
| `diagnose_clv_pinnacle.py` | `clv_block:370`; ROI via baseline | CLV e ROI Pinnacle, `results/clv_pinnacle_report.md` | sì | exit 0; report rigenerato |
| `elo_w025_confirmation.py` | usa `roi_1x2` della baseline | conferma peso Elo, `results/elo_w025_confirmation.md` | sì, via wrapper | non richiesto separatamente dal wrapper |
| `grid_search_ensemble_weight.py` | `_roi_rows:124` | scelta peso/ROI, `results/ensemble_weight_grid_search.md` | sì | exit 0; report rigenerato |
| `market_prior_xg.py` | selezione vettoriale nel blocco ROI, riga 236 | prior xG/ROI, `results/market_prior_xg_report.md` | sì | exit 0; report rigenerato |
| `market_values_versioned.py` | selezione vettoriale nel blocco ROI, riga 565 | fonti market value/ROI, `results/market_values_versioned_report.md` | sì | exit 0; report rigenerato |
| `gg_ng_calibration.py` | `simulate_roi:608` | ROI GG/NG, `results/gg_ng_calibration.md` | sì | exit 0; report rigenerato |
| `xg_rolling_walkforward.py` | `roi_1x2:251` | rolling xG/ROI, `xg_rolling_walkforward_results.txt` | sì | exit 0 |
| `generate_symmetric_decomposition_report.py` | selezioni inline righe 22 e 165 | decomposizione premio PR #24, `results/elo_symmetric_decomposition_report.md` | sì | **NON VERIFICABILE**: manca `audit/results/temp_stability_data.pkl`; `FileNotFoundError` |
| `generate_temporal_stability_report.py` | `get_roi_wr`, riga 42 | stabilità premio PR #24, `results/elo_temporal_stability_report.md` | sì | **NON VERIFICABILE**: stesso pickle mancante |

Ricerca residua eseguita: `grep -RInE 'argmax\(edge|edge.*> 0|edge.*>0|max\(edge' audit --include='*.py'`. Le occorrenze residue sono testo/docstring; non resta un selettore economico eseguibile con `argmax(edge de-vig)`.

## 2. Premio ROI PR #24

| Esito | Comando | Evidenza |
|---|---|---|
| OK | `gh pr view 24 --json commits,files,body` | commit PR `980e04851b91345e697e62fe7f50b425a3d6d2b5`; +5,20 pp e IC `[+0,36;+9,64]` dichiarati nel body |
| OK | `git fetch origin 980e048...; git show --stat 980e048...` | la PR aggiunge il report e due generatori successivi, ma **nessuno script che genera `elo_blend_impact_report.md`** |
| NON VERIFICABILE | rilancio stesso protocollo | mancano lo script produttore e `audit/results/temp_stability_data.pkl`; i generatori falliscono esattamente con `FileNotFoundError` |

Valore storico documentato: premio **+5,20 pp**, IC95% **[+0,36; +9,64]**, 1.752 partite; il report espone 1.752 puntate per ciascun modello. Nuovo premio, IC, numerosità e confronto proporzionale/Shin: **NON VERIFICABILI con gli input della PR #24**. Non sono sostituiti con il frame differente di `recalculate_ev.py`. In particolare non è possibile dimostrare sui dati originari che la sensibilità de-vig sparisca; per costruzione l’helper corrente dipende soltanto da `p` e quota grezza e non riceve una probabilità de-vigata.

## 3. EV pooled, bootstrap a blocchi

Blocchi: lega × stagione × data/giornata; 2.000 repliche, seed 240533. ROI in percentuale, delta = nuovo − vecchio.

| Modello | N vecchio | ROI vecchio | N EV | ROI EV | Δ ROI | IC95% Δ |
|---|---:|---:|---:|---:|---:|---:|
| Elo | 3.504 | -14,033 | 3.262 | -13,986 | +0,048 | [-2,565; +2,803] |
| Elo xG fix | 3.504 | -12,015 | 3.274 | -13,680 | -1,664 | [-4,184; +1,029] |
| Poisson | 3.504 | -11,759 | 3.000 | -13,350 | -1,590 | [-4,208; +1,050] |
| SoccerMath | 3.504 | -13,305 | 3.116 | -15,801 | -2,497 | [-4,768; -0,219] |
| SoccerMath xG fix | 3.504 | -13,215 | 3.116 | -15,096 | -1,882 | [-3,990; +0,257] |

La verifica per righe dà `new_rows_not_old=0`; 1.752 selezioni-cella sono rimosse. Dettaglio: `output/ev_recalculation.json`, pooled: `output/ev_pooled.csv`.

## 4. Totali pooled

Expanding principale: forza **20 pseudo-partite**, verso il base rate train della stessa lega. Variante `expanding_no_shrink`: prima partita ancorata al train solo perché non esiste alcun passato, poi frequenza grezza delle sole partite precedenti. Δ = modello − benchmark; negativo è migliore. Bootstrap a blocchi lega × stagione × data, 2.000 repliche.

| Mercato | Benchmark | Δ Brier [IC95%] | Δ LogLoss [IC95%] | BSS | Rel modello / bench | Res modello / bench | Verdetto |
|---|---|---|---|---:|---|---|---|
| GG/NG | train | +0,00186 [-0,00108;+0,00478] | +0,01828 [+0,00003;+0,04189] | -0,00752 | 0,00367 / 0,00033 | 0,00204 / 0,00005 | perde su LogLoss; Brier pari |
| GG/NG | expanding (20) | +0,00112 [-0,00198;+0,00427] | +0,01674 [-0,00145;+0,04033] | -0,00451 | 0,00367 / 0,00037 | 0,00204 / 0,00039 | pari |
| GG/NG | expanding no shrink | -0,00174 [-0,00541;+0,00187] | -0,06118 [-0,11318;-0,01357] | +0,00693 | 0,00367 / 0,00320 | 0,00204 / 0,00076 | vince LogLoss; Brier pari |
| GG/NG | ORACOLO | +0,00325 [+0,00010;+0,00644] | +0,02108 [+0,00289;+0,04472] | -0,01323 | 0,00367 / 0 | 0,00204 / 0,00141 | descrittivo |
| O/U 2.5 | train | -0,00068 [-0,00437;+0,00303] | -0,00134 [-0,00923;+0,00643] | +0,00275 | 0,00316 / 0,00016 | 0,00521 / 0,00252 | pari |
| O/U 2.5 | expanding (20) | -0,00231 [-0,00609;+0,00148] | -0,00468 [-0,01253;+0,00334] | +0,00931 | 0,00316 / 0,00050 | 0,00521 / 0,00163 | pari |
| O/U 2.5 | expanding no shrink | -0,00525 [-0,00934;-0,00103] | -0,08284 [-0,13219;-0,03996] | +0,02088 | 0,00316 / 0,00341 | 0,00521 / 0,00121 | vince |
| O/U 2.5 | ORACOLO | -0,00024 [-0,00395;+0,00352] | -0,00043 [-0,00832;+0,00742] | +0,00095 | 0,00316 / 0 | 0,00521 / 0,00216 | descrittivo |

La apparente vittoria contro expanding **non dipende dallo shrinkage**: è più forte contro la variante rumorosa senza shrinkage; col benchmark dichiarato e stabilizzato, O/U è pari e GG/NG è pari. File completo: `output/baserate_pooled.csv` e `output/baserate_benchmarks.csv`.

## 5. Origine Astra

Comandi su clone completo:

```text
git log --all -p -S'base rate' -- audit
git log --all -p -S'base_rate' -- audit
git log --all -p -S'banale' -- audit
git log --all -p -S'Brier dei Totali' -- audit
git log --all -p -G'base.rate' -- audit
git log --all -p -G'[Bb]anale' -- audit
git log --all -p -G'Brier.*[Tt]otal' -- audit
git log --all -p -G'[Aa]stra' -- audit
```

Le ricerche `-S` producono 0 righe. Le `-G` non trovano una costante base-rate/Astra; “Brier Totali” trova soltanto audit di modelli (`diagnose_elo_ensemble.py`), non una costante. **NON VERIFICABILE**: nessun commit/file/riga nella storia completa versionata contiene il calcolo attribuito ad Astra.

## Limiti di riproducibilità

Questi sono fatti preesistenti, non introdotti dalla PR #34, e non bloccano l'integrazione delle correzioni riproducibili contenute nella PR:

1. Il premio ROI **+5,20 pp** della PR #24, con IC95% **[+0,36; +9,64]**, non è riproducibile: lo script produttore non è mai stato versionato e manca l'input `audit/results/temp_stability_data.pkl`. Il risultato storico va quindi trattato come **non verificato**.
2. `generate_symmetric_decomposition_report.py` e `generate_temporal_stability_report.py` non sono rilanciabili per lo stesso input `audit/results/temp_stability_data.pkl` mancante.
3. La conclusione storica “Brier dei Totali peggiore del base rate” non ha una fonte rintracciabile nella storia Git completa. È sostituita dai risultati pooled, con bootstrap a blocchi, prodotti da questa PR.
