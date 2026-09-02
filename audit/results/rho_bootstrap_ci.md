# Bootstrap CI 95% — effetto del rho Dixon-Coles sul Brier Score

Campione: predizioni walk-forward no-leakage su **VALIDATION 2024/25 + TEST 2025/26**, tutte le 5 leghe. Stessa logica di `diagnose_dixon_coles_rho.py` (import in sola lettura: `run_walkforward_lambda`, `build_matrix`, `market_probs_from_matrix`). Nessuna modifica a SoccerMath/.

Confronto: **RHO_ZERO** (rho = 0, Poisson pura) vs **RHO_GLOBALE** (rho = -0.0470, gia' stimato su training pooled 5 leghe). Mercati analizzati: **1X2** e **GG/NG** (i due dove il rho ha mostrato un effetto nella diagnosi originale).

**Metodo.** Per ogni partita si calcola la differenza di Brier Score `d_i = Brier(RHO_ZERO)_i - Brier(RHO_GLOBALE)_i`. Bootstrap non parametrico: 2000 resample con reinserimento (stessa dimensione campionaria della lega), media di `d` per ogni resample, CI 95% = percentili 2.5-97.5. Seed fisso = 12345.

**Segno.** Differenza media `> 0` => RHO_GLOBALE **migliore** (Brier piu' basso col rho); `< 0` => rho peggiore. Se il CI 95% **include lo zero** l'effetto e' **indistinguibile dal rumore**; se il CI e' interamente sopra (o sotto) lo zero l'effetto e' un **segnale statisticamente robusto in questo campione**.

## Tabella: lega x mercato

| Lega | Mercato | N | Diff. media (Z-G) | CI95% basso | CI95% alto | Include zero | Verdetto |
|---|---|---|---:|---:|---:|:---:|---|
| Serie A | 1X2 | 760 | +0.000705 | -0.000312 | +0.001737 | si | rumore (CI include 0) |
| Serie A | GG/NG | 760 | +0.000356 | -0.000388 | +0.001149 | si | rumore (CI include 0) |
| Premier League | 1X2 | 760 | +0.000831 | -0.000047 | +0.001762 | si | rumore (CI include 0) |
| Premier League | GG/NG | 760 | +0.000500 | -0.000212 | +0.001213 | si | rumore (CI include 0) |
| La Liga | 1X2 | 760 | +0.000118 | -0.000909 | +0.001145 | si | rumore (CI include 0) |
| La Liga | GG/NG | 760 | +0.001859 | +0.001156 | +0.002612 | no | robusto: rho MEGLIO |
| Bundesliga | 1X2 | 612 | +0.000630 | -0.000335 | +0.001638 | si | rumore (CI include 0) |
| Bundesliga | GG/NG | 612 | +0.000610 | -0.000100 | +0.001343 | si | rumore (CI include 0) |
| Ligue 1 | 1X2 | 612 | -0.000309 | -0.001279 | +0.000746 | si | rumore (CI include 0) |
| Ligue 1 | GG/NG | 612 | +0.000301 | -0.000473 | +0.001093 | si | rumore (CI include 0) |

## Aggregato — 5 leghe insieme (pooling dei resample)

Resample con reinserimento sul campione poolato di tutte le partite delle 5 leghe (N = 3504).

| Campione | Mercato | N | Diff. media (Z-G) | CI95% basso | CI95% alto | Include zero | Verdetto |
|---|---|---|---:|---:|---:|:---:|---|
| POOLED 5 leghe | 1X2 | 3504 | +0.000415 | -0.000048 | +0.000872 | si | rumore (CI include 0) |
| POOLED 5 leghe | GG/NG | 3504 | +0.000748 | +0.000408 | +0.001094 | no | robusto: rho MEGLIO |

## Sintesi

- Combinazioni lega x mercato analizzate: **10** (5 leghe x 2 mercati).
- CI 95% che **NON** include lo zero (segnale robusto in questo campione): **1/10**: La Liga/GG/NG.
- CI 95% che include lo zero (indistinguibile dal rumore): **9/10**.
- Aggregato 1X2: diff. media +0.000415, CI95% [-0.000048, +0.000872] — include lo zero.
- Aggregato GG/NG: diff. media +0.000748, CI95% [+0.000408, +0.001094] — non include lo zero.

**Lettura.** Le differenze di Brier in gioco sono minuscole (ordine 1e-3 o inferiore per partita): il bootstrap serve proprio a capire se, pur piccole, sono sistematiche o solo rumore di campionamento. Dove il CI include lo zero, il segno osservato della differenza media non e' affidabile e il rho e' di fatto ininfluente su quel mercato/lega in questo campione. L'aggregato, avendo la N piu' grande, e' il test piu' potente per un effetto sistematico.

## Note

- rho fisso = -0.0470 (RHO_GLOBALE gia' stimato via MLE su training 2022/23+2023/24 in `diagnose_dixon_coles_rho.py`; qui NON viene ristimato).
- Brier per-partita: 1X2 su 3 classi (1/X/2), GG/NG su 2 classi. La differenza usa la stessa realizzazione e gli stessi lambda walk-forward per entrambi i valori di rho, quindi e' un confronto appaiato (paired) partita per partita.
- Bootstrap: 2000 resample, seed 12345 (`numpy.random.default_rng`), percentili 2.5/97.5. Nessun file di SoccerMath/ modificato.

