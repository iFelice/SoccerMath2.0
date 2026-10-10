# Griglia implicita nelle quote: fattibilita' sui mercati gol (sola lettura)

Generato da `audit/griglia_implicita.py` il 2026-10-10T15:40:30Z (commit `e0eabb2c8b35`, branch `arena/9ed43c63-soccermath2-0`). Nessuna modifica a `SoccerMath/` (app.py incluso), nessun replay `--write`, nessuna chiave API. Probabilita' di `topmix_mercato_v3` invariate: il codice non le tocca.

**Stato: fattibilita' di audit. Nessuna regola di selezione delle giocate cambia.**

## 0. Ambiente e fonti

| voce | valore |
|---|---|
| Python | 3.11.2 |
| numpy / pandas / scipy | numpy 2.4.6, pandas 3.0.6, scipy 1.17.1 |
| Campione | 2024/25 + 2025/26, 5 leghe (CSV football-data in SoccerMath/database) |
| Griglia implicita | Dixon-Coles, (lambda, mu, rho) per partita su 1X2 + O/U 2,5 de-vig proporzionale; tau come `models/dixon_coles.tau_correction`; griglia 0..15 |
| Griglia Poisson implicita (confronto) | stesso fit con rho = 0 |
| Modello di produzione | Poisson walk-forward: `ppda_residual_test.production_totali` + `app.get_full_poisson_two_heads` intercettata (1X2 dalla testa 1X2, O/U e Gol dalla testa Totali) |
| Combinazioni del modello | griglia Poisson congiunta dai lambda puri della testa Totali (limite dichiarato) |
| Bootstrap | 2000 repliche, blocchi lega x stagione x data, IC 95% percentile, seme 20261010 |
| Tempo di esecuzione | 262 s |

### 0.1 Parita' della cattura di produzione (intercettata vs banco)

Le uscite intercettate devono coincidere con le colonne del banco `production_totali`; scarto atteso 0.

| lega | righe | max |u25 intercettato − banco| | max |gg intercettato − banco| | max |1+X+2 − 1| |
|---|---|---|---|---|
| Serie A | 1570 | 0.00e+00 | 0.00e+00 | 1.59e-05 |
| Premier League | 1570 | 0.00e+00 | 0.00e+00 | 1.93e-04 |
| La Liga | 1590 | 0.00e+00 | 0.00e+00 | 5.63e-05 |
| Bundesliga | 1261 | 0.00e+00 | 0.00e+00 | 1.60e-03 |
| Ligue 1 | 1344 | 0.00e+00 | 0.00e+00 | 8.34e-05 |

## 1. Copertura per lega e stagione (prima di qualsiasi valutazione)

Righe dei CSV, righe con modello, quote disponibili per il campione. Il campione principale usa solo le partite con modello E terna B365 1X2 e B365 O/U 2,5 complete.

| lega | stagione | partite_csv | con_modello | B365 1X2 ant. | B365 O/U 2,5 ant. | Pinnacle 1X2 chiusura | Pinnacle O/U 2,5 chiusura | Pinnacle chiusura completa (1X2+O/U) |
|---|---|---|---|---|---|---|---|---|
| Serie A | 2024/25 | 380 | 380 | 380 | 380 | 380 | 380 | 380 |
| Serie A | 2025/26 | 380 | 380 | 380 | 380 | 198 | 198 | 198 |
| Premier League | 2024/25 | 380 | 380 | 380 | 380 | 380 | 377 | 377 |
| Premier League | 2025/26 | 380 | 380 | 380 | 380 | 210 | 210 | 210 |
| La Liga | 2024/25 | 380 | 380 | 380 | 380 | 380 | 378 | 378 |
| La Liga | 2025/26 | 380 | 380 | 380 | 380 | 188 | 189 | 188 |
| Bundesliga | 2024/25 | 306 | 306 | 306 | 306 | 306 | 297 | 297 |
| Bundesliga | 2025/26 | 306 | 306 | 306 | 306 | 149 | 142 | 142 |
| Ligue 1 | 2024/25 | 306 | 306 | 306 | 306 | 306 | 304 | 304 |
| Ligue 1 | 2025/26 | 306 | 306 | 306 | 306 | 153 | 152 | 152 |

Campione principale: **3504** partite (2024/25 + 2025/26). Sottocampione Pinnacle chiusura completa (sensibilita'): **2623**.

Nota: su 2025/26 le quote Pinnacle di chiusura (PSC*) sono presenti solo per una parte delle partite (CSV football-data, campo non sempre valorizzato): e' la ragione del sottocampione.

## 2. Verifica di riproduzione della griglia implicita

Errore massimo |predetto − di partenza| sulle 4 quote di partenza (1, X, 2, Over 2,5), per partita, sul campione principale.

| griglia | max | p99 | mediana | partite con residuo > 1e-6 | convergenza |
|---|---|---|---|---|---|
| Dixon-Coles (rho stimato) | 0,00000000 | 0,00000000 | 0,00000000 | 0 | 3504 / 3504 |
| Poisson puro implicito (rho = 0) | 0,06103448 | 0,03838828 | 0,01568880 | 3504 | 3504 / 3504 |

Lettura: la griglia Dixon-Coles ha 3 parametri per 4 quote di partenza, quindi riproduce il punto esatto quando il sistema e' risolvibile; il Poisson puro ha 2 parametri e NON riproduce in generale tutte e 4 le quote. Il residuo del Poisson puro e' informazione, non un errore del codice.

Rho stimati (DC): mediana -0,078, 5°-95° percentile [-0,146; 0,020]; quota di partite al bordo di rho (|rho| ≥ 0,49): 0,0 %.

## 3. Brier per mercato: griglia implicita vs modello di produzione (campione principale)

Brier binario medio (piu' basso = meglio). Δ = Brier(modello) − Brier(griglia implicita): Δ > 0 significa che la griglia implicita e' migliore. IC 95% con bootstrap a blocchi. Regola dichiarata: la griglia implicita sostituisce il modello sul mercato se il suo Brier e' migliore con IC che esclude lo zero.

| mercato | n | Brier griglia implicita (DC) | Brier modello (Poisson di produzione) | Δ modello − griglia [IC 95%] | esito della regola |
|---|---|---|---|---|---|
| 1 | 3504 | 0,2066 | 0,2182 | 0,0116 [0,0084; 0,0149] | SOSTITUISCE (griglia implicita) |
| X | 3504 | 0,1856 | 0,1878 | 0,0022 [0,0009; 0,0035] | SOSTITUISCE (griglia implicita) |
| 2 | 3504 | 0,1858 | 0,1954 | 0,0095 [0,0064; 0,0127] | SOSTITUISCE (griglia implicita) |
| 1X | 3504 | 0,1858 | 0,1954 | 0,0095 [0,0064; 0,0127] | SOSTITUISCE (griglia implicita) |
| X2 | 3504 | 0,2066 | 0,2182 | 0,0116 [0,0086; 0,0147] | SOSTITUISCE (griglia implicita) |
| 12 | 3504 | 0,1856 | 0,1878 | 0,0022 [0,0010; 0,0034] | SOSTITUISCE (griglia implicita) |
| Over 1.5 | 3504 | 0,1719 | 0,1743 | 0,0024 [0,0012; 0,0037] | SOSTITUISCE (griglia implicita) |
| Under 1.5 | 3504 | 0,1719 | 0,1743 | 0,0024 [0,0013; 0,0036] | SOSTITUISCE (griglia implicita) |
| Over 2.5 | 3504 | 0,2399 | 0,2446 | 0,0046 [0,0027; 0,0066] | SOSTITUISCE (griglia implicita) |
| Under 2.5 | 3504 | 0,2399 | 0,2446 | 0,0046 [0,0028; 0,0067] | SOSTITUISCE (griglia implicita) |
| Over 3.5 | 3504 | 0,2038 | 0,2064 | 0,0027 [0,0008; 0,0045] | SOSTITUISCE (griglia implicita) |
| Under 3.5 | 3504 | 0,2038 | 0,2064 | 0,0027 [0,0008; 0,0045] | SOSTITUISCE (griglia implicita) |
| Gol | 3504 | 0,2451 | 0,2476 | 0,0025 [0,0011; 0,0040] | SOSTITUISCE (griglia implicita) |
| No Gol | 3504 | 0,2451 | 0,2476 | 0,0025 [0,0009; 0,0039] | SOSTITUISCE (griglia implicita) |
| 1+Over 1.5 | 3504 | 0,1923 | 0,2016 | 0,0093 [0,0069; 0,0117] | SOSTITUISCE (griglia implicita) |
| 2+Over 1.5 | 3504 | 0,1645 | 0,1702 | 0,0057 [0,0035; 0,0077] | SOSTITUISCE (griglia implicita) |
| 1X+Over 1.5 | 3504 | 0,2237 | 0,2312 | 0,0075 [0,0052; 0,0097] | SOSTITUISCE (griglia implicita) |
| X2+Under 3.5 | 3504 | 0,2219 | 0,2282 | 0,0063 [0,0043; 0,0084] | SOSTITUISCE (griglia implicita) |
| 1+Gol | 3504 | 0,1555 | 0,1579 | 0,0023 [0,0012; 0,0035] | SOSTITUISCE (griglia implicita) |
| 2+Gol | 3504 | 0,1209 | 0,1231 | 0,0022 [0,0011; 0,0033] | SOSTITUISCE (griglia implicita) |

**Attenzione alla lettura.** (1) Le 20 righe non sono 20 prove indipendenti: 1X e' il complemento di 2, X2 di 1, 12 di X, Under di Over (stessa linea), No Gol di Gol. Per costruzione hanno lo stesso Brier: le informazioni distinte sono 10. (2) La griglia implicita viene dalle quote bet365 pre-partita de-vig: il vantaggio sul Brier misura quanta informazione contengono le quote, NON un edge sul banco. Il Brier non dice nulla sul valore di una giocata a quota.

### 3.1 Confronto aggiuntivo: Dixon-Coles implicito vs Poisson puro implicito

Stesso input (1X2 + O/U 2,5 B365), solo rho diverso. Non e' la regola di sostituzione: serve a dire se il rho stimato dalle quote aggiunge informazione.

| mercato | Brier DC | Brier Poisson puro | Δ Poisson − DC [IC 95%] |
|---|---|---|---|
| 1 | 0,2066 | 0,2069 | 0,0003 [0,0000; 0,0005] |
| X | 0,1856 | 0,1860 | 0,0004 [-0,0001; 0,0009] |
| 2 | 0,1858 | 0,1858 | 0,0000 [-0,0003; 0,0003] |
| 1X | 0,1858 | 0,1858 | 0,0000 [-0,0003; 0,0003] |
| X2 | 0,2066 | 0,2069 | 0,0003 [-0,0000; 0,0005] |
| 12 | 0,1856 | 0,1860 | 0,0004 [-0,0002; 0,0009] |
| Over 1.5 | 0,1719 | 0,1720 | 0,0001 [-0,0002; 0,0006] |
| Under 1.5 | 0,1719 | 0,1720 | 0,0001 [-0,0003; 0,0005] |
| Over 2.5 | 0,2399 | 0,2400 | 0,0001 [-0,0001; 0,0003] |
| Under 2.5 | 0,2399 | 0,2400 | 0,0001 [-0,0001; 0,0003] |
| Over 3.5 | 0,2038 | 0,2037 | -0,0000 [-0,0002; 0,0001] |
| Under 3.5 | 0,2038 | 0,2037 | -0,0000 [-0,0002; 0,0001] |
| Gol | 0,2451 | 0,2457 | 0,0006 [0,0002; 0,0011] |
| No Gol | 0,2451 | 0,2457 | 0,0006 [0,0002; 0,0011] |
| 1+Over 1.5 | 0,1923 | 0,1922 | -0,0001 [-0,0002; 0,0001] |
| 2+Over 1.5 | 0,1645 | 0,1645 | 0,0000 [-0,0001; 0,0001] |
| 1X+Over 1.5 | 0,2237 | 0,2238 | 0,0001 [-0,0004; 0,0005] |
| X2+Under 3.5 | 0,2219 | 0,2220 | 0,0001 [-0,0001; 0,0003] |
| 1+Gol | 0,1555 | 0,1556 | 0,0001 [-0,0000; 0,0001] |
| 2+Gol | 0,1209 | 0,1209 | -0,0000 [-0,0001; 0,0000] |

## 4. Calibrazione per fasce di probabilita' (campione principale)

Per ogni mercato: partite con probabilita' dichiarata dell'evento nella fascia; n, probabilita' media dichiarata (p) e frequenza osservata (f). Celle vuote = n = 0.

### 4.1 Griglia implicita (Dixon-Coles)

| mercato | 0,50-0,60 | 0,60-0,70 | 0,70-0,80 | 0,80-0,90 | ≥0,90 |
|---|---|---|---|---|---|
| 1 | n=551; p=0,548; f=0,525 | n=397; p=0,650; f=0,673 | n=236; p=0,745; f=0,758 | n=65; p=0,834; f=0,908 | n=1; p=0,907; f=1,000 |
| X | — | — | — | — | — |
| 2 | n=290; p=0,548; f=0,579 | n=156; p=0,638; f=0,635 | n=54; p=0,738; f=0,852 | n=5; p=0,829; f=1,000 | — |
| 1X | n=419; p=0,553; f=0,511 | n=694; p=0,652; f=0,663 | n=924; p=0,750; f=0,747 | n=745; p=0,847; f=0,854 | n=217; p=0,923; f=0,935 |
| X2 | n=726; p=0,551; f=0,547 | n=699; p=0,648; f=0,667 | n=492; p=0,747; f=0,770 | n=308; p=0,839; f=0,880 | n=29; p=0,916; f=1,000 |
| 12 | — | n=347; p=0,686; f=0,669 | n=2578; p=0,741; f=0,738 | n=554; p=0,832; f=0,838 | n=25; p=0,913; f=0,920 |
| Over 1.5 | n=32; p=0,576; f=0,562 | n=455; p=0,669; f=0,681 | n=1827; p=0,755; f=0,752 | n=1133; p=0,838; f=0,838 | n=57; p=0,911; f=0,947 |
| Under 1.5 | — | — | — | — | — |
| Over 2.5 | n=1284; p=0,544; f=0,558 | n=671; p=0,633; f=0,629 | n=187; p=0,727; f=0,733 | n=4; p=0,827; f=0,750 | — |
| Under 2.5 | n=1091; p=0,544; f=0,558 | n=262; p=0,631; f=0,588 | n=22; p=0,710; f=0,727 | — | — |
| Over 3.5 | n=118; p=0,535; f=0,534 | n=10; p=0,626; f=0,700 | — | — | — |
| Under 3.5 | n=413; p=0,557; f=0,552 | n=1338; p=0,657; f=0,660 | n=1341; p=0,749; f=0,761 | n=284; p=0,829; f=0,831 | — |
| Gol | n=1794; p=0,548; f=0,566 | n=525; p=0,630; f=0,646 | n=19; p=0,715; f=0,632 | — | — |
| No Gol | n=1085; p=0,536; f=0,535 | n=81; p=0,620; f=0,494 | — | — | — |
| 1+Over 1.5 | n=379; p=0,549; f=0,525 | n=212; p=0,647; f=0,675 | n=77; p=0,740; f=0,779 | n=13; p=0,816; f=0,769 | — |
| 2+Over 1.5 | n=139; p=0,540; f=0,482 | n=62; p=0,640; f=0,677 | n=10; p=0,743; f=0,700 | — | — |
| 1X+Over 1.5 | n=841; p=0,549; f=0,553 | n=674; p=0,646; f=0,659 | n=365; p=0,743; f=0,756 | n=113; p=0,835; f=0,814 | n=1; p=0,911; f=1,000 |
| X2+Under 3.5 | n=701; p=0,540; f=0,561 | n=96; p=0,626; f=0,750 | — | — | — |
| 1+Gol | — | — | — | — | — |
| 2+Gol | — | — | — | — | — |

### 4.2 Modello di produzione (Poisson)

| mercato | 0,50-0,60 | 0,60-0,70 | 0,70-0,80 | 0,80-0,90 | ≥0,90 |
|---|---|---|---|---|---|
| 1 | n=406; p=0,548; f=0,485 | n=376; p=0,651; f=0,582 | n=305; p=0,748; f=0,685 | n=192; p=0,843; f=0,740 | n=53; p=0,934; f=0,774 |
| X | — | — | — | — | — |
| 2 | n=354; p=0,547; f=0,486 | n=273; p=0,647; f=0,516 | n=151; p=0,748; f=0,623 | n=71; p=0,841; f=0,718 | n=8; p=0,926; f=1,000 |
| 1X | n=431; p=0,553; f=0,606 | n=542; p=0,654; f=0,697 | n=595; p=0,750; f=0,745 | n=609; p=0,852; f=0,810 | n=470; p=0,940; f=0,902 |
| X2 | n=515; p=0,550; f=0,538 | n=552; p=0,650; f=0,621 | n=473; p=0,749; f=0,721 | n=436; p=0,847; f=0,782 | n=196; p=0,933; f=0,872 |
| 12 | — | n=232; p=0,682; f=0,672 | n=2217; p=0,754; f=0,732 | n=912; p=0,839; f=0,783 | n=143; p=0,929; f=0,895 |
| Over 1.5 | n=31; p=0,577; f=0,645 | n=593; p=0,667; f=0,708 | n=1765; p=0,754; f=0,766 | n=1086; p=0,834; f=0,815 | n=29; p=0,912; f=0,966 |
| Under 1.5 | — | — | — | — | — |
| Over 2.5 | n=1348; p=0,550; f=0,560 | n=703; p=0,639; f=0,589 | n=91; p=0,731; f=0,747 | n=3; p=0,824; f=1,000 | — |
| Under 2.5 | n=1087; p=0,544; f=0,530 | n=261; p=0,630; f=0,571 | n=11; p=0,714; f=0,818 | — | — |
| Over 3.5 | n=69; p=0,533; f=0,551 | n=6; p=0,634; f=0,667 | — | — | — |
| Under 3.5 | n=482; p=0,562; f=0,606 | n=1290; p=0,653; f=0,643 | n=1362; p=0,746; f=0,755 | n=295; p=0,825; f=0,820 | — |
| Gol | n=1735; p=0,548; f=0,558 | n=713; p=0,631; f=0,595 | n=11; p=0,713; f=0,545 | — | — |
| No Gol | n=989; p=0,536; f=0,507 | n=56; p=0,622; f=0,536 | — | — | — |
| 1+Over 1.5 | n=295; p=0,542; f=0,580 | n=104; p=0,640; f=0,596 | n=33; p=0,738; f=0,788 | n=4; p=0,834; f=0,250 | — |
| 2+Over 1.5 | n=69; p=0,537; f=0,536 | n=23; p=0,635; f=0,565 | n=3; p=0,729; f=1,000 | — | — |
| 1X+Over 1.5 | n=1109; p=0,549; f=0,572 | n=612; p=0,645; f=0,670 | n=204; p=0,739; f=0,755 | n=46; p=0,829; f=0,826 | n=3; p=0,907; f=0,667 |
| X2+Under 3.5 | n=530; p=0,538; f=0,585 | n=50; p=0,623; f=0,580 | — | — | — |
| 1+Gol | — | — | — | — | — |
| 2+Gol | — | — | — | — | — |

## 5. Fascia alta (≥ 0,65): quella da cui si scelgono le giocate

Calibrazione separata nella fascia alta. Per ogni mercato e fonte: n, p media dichiarata, frequenza osservata, differenza f − p (in punti percentuali).

| mercato | griglia implicita (≥ 0,65) | modello di produzione (≥ 0,65) |
|---|---|---|
| 1 | n=500; p=0,729; f=0,778; f−p=4,9 pt | n=747; p=0,767; f=0,695; f−p=-7,2 pt |
| X | — | — |
| 2 | n=122; p=0,707; f=0,762; f−p=5,6 pt | n=360; p=0,743; f=0,606; f−p=-13,8 pt |
| 1X | n=2259; p=0,786; f=0,793; f−p=0,7 pt | n=1988; p=0,815; f=0,796; f−p=-1,8 pt |
| X2 | n=1143; p=0,756; f=0,786; f−p=2,9 pt | n=1380; p=0,791; f=0,742; f−p=-4,9 pt |
| 12 | n=3502; p=0,752; f=0,748; f−p=-0,3 pt | n=3491; p=0,779; f=0,748; f−p=-3,1 pt |
| Over 1.5 | n=3356; p=0,778; f=0,779; f−p=0,1 pt | n=3333; p=0,771; f=0,777; f−p=0,6 pt |
| Under 1.5 | — | — |
| Over 2.5 | n=409; p=0,695; f=0,689; f−p=-0,5 pt | n=334; p=0,689; f=0,665; f−p=-2,5 pt |
| Under 2.5 | n=83; p=0,676; f=0,687; f−p=1,1 pt | n=69; p=0,675; f=0,652; f−p=-2,2 pt |
| Over 3.5 | n=3; p=0,667; f=0,667; f−p=-0,1 pt | n=2; p=0,669; f=1,000; f−p=33,1 pt |
| Under 3.5 | n=2484; p=0,733; f=0,740; f−p=0,7 pt | n=2367; p=0,735; f=0,734; f−p=-0,1 pt |
| Gol | n=122; p=0,674; f=0,639; f−p=-3,5 pt | n=166; p=0,671; f=0,639; f−p=-3,2 pt |
| No Gol | n=4; p=0,663; f=0,500; f−p=-16,3 pt | n=5; p=0,659; f=0,800; f−p=14,1 pt |
| 1+Over 1.5 | n=180; p=0,714; f=0,767; f−p=5,2 pt | n=74; p=0,711; f=0,689; f−p=-2,2 pt |
| 2+Over 1.5 | n=30; p=0,698; f=0,700; f−p=0,2 pt | n=8; p=0,690; f=0,875; f−p=18,5 pt |
| 1X+Over 1.5 | n=772; p=0,730; f=0,750; f−p=2,0 pt | n=497; p=0,716; f=0,724; f−p=0,8 pt |
| X2+Under 3.5 | n=11; p=0,665; f=0,818; f−p=15,4 pt | n=5; p=0,675; f=0,800; f−p=12,5 pt |
| 1+Gol | — | — |
| 2+Gol | — | — |

Fasce alte per mercato (griglia implicita): **0,65-0,70**; **0,70-0,80**; **0,80-0,90**; **≥0,90**.

| mercato | griglia implicita: fasce ≥0,65 | modello: fasce ≥0,65 |
|---|---|---|
| 1 | 0,65-0,70: n=198, p=0,68, f=0,76 · 0,70-0,80: n=236, p=0,74, f=0,76 · 0,80-0,90: n=65, p=0,83, f=0,91 · ≥0,90: n=1, p=0,91, f=1,00 | 0,65-0,70: n=197, p=0,68, f=0,64 · 0,70-0,80: n=305, p=0,75, f=0,69 · 0,80-0,90: n=192, p=0,84, f=0,74 · ≥0,90: n=53, p=0,93, f=0,77 |
| X | 0,65-0,70: n=0 · 0,70-0,80: n=0 · 0,80-0,90: n=0 · ≥0,90: n=0 | 0,65-0,70: n=0 · 0,70-0,80: n=0 · 0,80-0,90: n=0 · ≥0,90: n=0 |
| 2 | 0,65-0,70: n=63, p=0,67, f=0,67 · 0,70-0,80: n=54, p=0,74, f=0,85 · 0,80-0,90: n=5, p=0,83, f=1,00 · ≥0,90: n=0 | 0,65-0,70: n=130, p=0,67, f=0,50 · 0,70-0,80: n=151, p=0,75, f=0,62 · 0,80-0,90: n=71, p=0,84, f=0,72 · ≥0,90: n=8, p=0,93, f=1,00 |
| 1X | 0,65-0,70: n=373, p=0,67, f=0,70 · 0,70-0,80: n=924, p=0,75, f=0,75 · 0,80-0,90: n=745, p=0,85, f=0,85 · ≥0,90: n=217, p=0,92, f=0,94 | 0,65-0,70: n=314, p=0,68, f=0,71 · 0,70-0,80: n=595, p=0,75, f=0,74 · 0,80-0,90: n=609, p=0,85, f=0,81 · ≥0,90: n=470, p=0,94, f=0,90 |
| X2 | 0,65-0,70: n=314, p=0,68, f=0,70 · 0,70-0,80: n=492, p=0,75, f=0,77 · 0,80-0,90: n=308, p=0,84, f=0,88 · ≥0,90: n=29, p=0,92, f=1,00 | 0,65-0,70: n=275, p=0,68, f=0,62 · 0,70-0,80: n=473, p=0,75, f=0,72 · 0,80-0,90: n=436, p=0,85, f=0,78 · ≥0,90: n=196, p=0,93, f=0,87 |
| 12 | 0,65-0,70: n=345, p=0,69, f=0,67 · 0,70-0,80: n=2578, p=0,74, f=0,74 · 0,80-0,90: n=554, p=0,83, f=0,84 · ≥0,90: n=25, p=0,91, f=0,92 | 0,65-0,70: n=219, p=0,68, f=0,67 · 0,70-0,80: n=2217, p=0,75, f=0,73 · 0,80-0,90: n=912, p=0,84, f=0,78 · ≥0,90: n=143, p=0,93, f=0,90 |
| Over 1.5 | 0,65-0,70: n=339, p=0,68, f=0,70 · 0,70-0,80: n=1827, p=0,75, f=0,75 · 0,80-0,90: n=1133, p=0,84, f=0,84 · ≥0,90: n=57, p=0,91, f=0,95 | 0,65-0,70: n=453, p=0,68, f=0,72 · 0,70-0,80: n=1765, p=0,75, f=0,77 · 0,80-0,90: n=1086, p=0,83, f=0,81 · ≥0,90: n=29, p=0,91, f=0,97 |
| Under 1.5 | 0,65-0,70: n=0 · 0,70-0,80: n=0 · 0,80-0,90: n=0 · ≥0,90: n=0 | 0,65-0,70: n=0 · 0,70-0,80: n=0 · 0,80-0,90: n=0 · ≥0,90: n=0 |
| Over 2.5 | 0,65-0,70: n=218, p=0,66, f=0,65 · 0,70-0,80: n=187, p=0,73, f=0,73 · 0,80-0,90: n=4, p=0,83, f=0,75 · ≥0,90: n=0 | 0,65-0,70: n=240, p=0,67, f=0,63 · 0,70-0,80: n=91, p=0,73, f=0,75 · 0,80-0,90: n=3, p=0,82, f=1,00 · ≥0,90: n=0 |
| Under 2.5 | 0,65-0,70: n=61, p=0,66, f=0,67 · 0,70-0,80: n=22, p=0,71, f=0,73 · 0,80-0,90: n=0 · ≥0,90: n=0 | 0,65-0,70: n=58, p=0,67, f=0,62 · 0,70-0,80: n=11, p=0,71, f=0,82 · 0,80-0,90: n=0 · ≥0,90: n=0 |
| Over 3.5 | 0,65-0,70: n=3, p=0,67, f=0,67 · 0,70-0,80: n=0 · 0,80-0,90: n=0 · ≥0,90: n=0 | 0,65-0,70: n=2, p=0,67, f=1,00 · 0,70-0,80: n=0 · 0,80-0,90: n=0 · ≥0,90: n=0 |
| Under 3.5 | 0,65-0,70: n=859, p=0,68, f=0,68 · 0,70-0,80: n=1341, p=0,75, f=0,76 · 0,80-0,90: n=284, p=0,83, f=0,83 · ≥0,90: n=0 | 0,65-0,70: n=710, p=0,67, f=0,66 · 0,70-0,80: n=1362, p=0,75, f=0,75 · 0,80-0,90: n=295, p=0,82, f=0,82 · ≥0,90: n=0 |
| Gol | 0,65-0,70: n=103, p=0,67, f=0,64 · 0,70-0,80: n=19, p=0,71, f=0,63 · 0,80-0,90: n=0 · ≥0,90: n=0 | 0,65-0,70: n=155, p=0,67, f=0,65 · 0,70-0,80: n=11, p=0,71, f=0,55 · 0,80-0,90: n=0 · ≥0,90: n=0 |
| No Gol | 0,65-0,70: n=4, p=0,66, f=0,50 · 0,70-0,80: n=0 · 0,80-0,90: n=0 · ≥0,90: n=0 | 0,65-0,70: n=5, p=0,66, f=0,80 · 0,70-0,80: n=0 · 0,80-0,90: n=0 · ≥0,90: n=0 |
| 1+Over 1.5 | 0,65-0,70: n=90, p=0,68, f=0,76 · 0,70-0,80: n=77, p=0,74, f=0,78 · 0,80-0,90: n=13, p=0,82, f=0,77 · ≥0,90: n=0 | 0,65-0,70: n=37, p=0,67, f=0,65 · 0,70-0,80: n=33, p=0,74, f=0,79 · 0,80-0,90: n=4, p=0,83, f=0,25 · ≥0,90: n=0 |
| 2+Over 1.5 | 0,65-0,70: n=20, p=0,68, f=0,70 · 0,70-0,80: n=10, p=0,74, f=0,70 · 0,80-0,90: n=0 · ≥0,90: n=0 | 0,65-0,70: n=5, p=0,67, f=0,80 · 0,70-0,80: n=3, p=0,73, f=1,00 · 0,80-0,90: n=0 · ≥0,90: n=0 |
| 1X+Over 1.5 | 0,65-0,70: n=293, p=0,67, f=0,72 · 0,70-0,80: n=365, p=0,74, f=0,76 · 0,80-0,90: n=113, p=0,83, f=0,81 · ≥0,90: n=1, p=0,91, f=1,00 | 0,65-0,70: n=244, p=0,67, f=0,68 · 0,70-0,80: n=204, p=0,74, f=0,75 · 0,80-0,90: n=46, p=0,83, f=0,83 · ≥0,90: n=3, p=0,91, f=0,67 |
| X2+Under 3.5 | 0,65-0,70: n=11, p=0,66, f=0,82 · 0,70-0,80: n=0 · 0,80-0,90: n=0 · ≥0,90: n=0 | 0,65-0,70: n=5, p=0,67, f=0,80 · 0,70-0,80: n=0 · 0,80-0,90: n=0 · ≥0,90: n=0 |
| 1+Gol | 0,65-0,70: n=0 · 0,70-0,80: n=0 · 0,80-0,90: n=0 · ≥0,90: n=0 | 0,65-0,70: n=0 · 0,70-0,80: n=0 · 0,80-0,90: n=0 · ≥0,90: n=0 |
| 2+Gol | 0,65-0,70: n=0 · 0,70-0,80: n=0 · 0,80-0,90: n=0 · ≥0,90: n=0 | 0,65-0,70: n=0 · 0,70-0,80: n=0 · 0,80-0,90: n=0 · ≥0,90: n=0 |

## 6. Conclusione per mercato (regola dichiarata)

Regola applicata come dichiarata prima di guardare i risultati: la griglia implicita sostituisce il modello sul mercato se il suo Brier e' migliore con IC 95% che esclude lo zero; altrimenti "nessuna differenza dimostrata". La decisione e' riportata per tutti i 20 mercati, anche se sono 10 informazioni distinte (vedi §3).

| mercato | decisione | motivo |
|---|---|---|
| 1 | SOSTITUISCE (griglia implicita) | Δ 0,0116 [0,0084; 0,0149], n=3504 |
| X | SOSTITUISCE (griglia implicita) | Δ 0,0022 [0,0009; 0,0035], n=3504 |
| 2 | SOSTITUISCE (griglia implicita) | Δ 0,0095 [0,0064; 0,0127], n=3504 |
| 1X | SOSTITUISCE (griglia implicita) | Δ 0,0095 [0,0064; 0,0127], n=3504 |
| X2 | SOSTITUISCE (griglia implicita) | Δ 0,0116 [0,0086; 0,0147], n=3504 |
| 12 | SOSTITUISCE (griglia implicita) | Δ 0,0022 [0,0010; 0,0034], n=3504 |
| Over 1.5 | SOSTITUISCE (griglia implicita) | Δ 0,0024 [0,0012; 0,0037], n=3504 |
| Under 1.5 | SOSTITUISCE (griglia implicita) | Δ 0,0024 [0,0013; 0,0036], n=3504 |
| Over 2.5 | SOSTITUISCE (griglia implicita) | Δ 0,0046 [0,0027; 0,0066], n=3504 |
| Under 2.5 | SOSTITUISCE (griglia implicita) | Δ 0,0046 [0,0028; 0,0067], n=3504 |
| Over 3.5 | SOSTITUISCE (griglia implicita) | Δ 0,0027 [0,0008; 0,0045], n=3504 |
| Under 3.5 | SOSTITUISCE (griglia implicita) | Δ 0,0027 [0,0008; 0,0045], n=3504 |
| Gol | SOSTITUISCE (griglia implicita) | Δ 0,0025 [0,0011; 0,0040], n=3504 |
| No Gol | SOSTITUISCE (griglia implicita) | Δ 0,0025 [0,0009; 0,0039], n=3504 |
| 1+Over 1.5 | SOSTITUISCE (griglia implicita) | Δ 0,0093 [0,0069; 0,0117], n=3504 |
| 2+Over 1.5 | SOSTITUISCE (griglia implicita) | Δ 0,0057 [0,0035; 0,0077], n=3504 |
| 1X+Over 1.5 | SOSTITUISCE (griglia implicita) | Δ 0,0075 [0,0052; 0,0097], n=3504 |
| X2+Under 3.5 | SOSTITUISCE (griglia implicita) | Δ 0,0063 [0,0043; 0,0084], n=3504 |
| 1+Gol | SOSTITUISCE (griglia implicita) | Δ 0,0023 [0,0012; 0,0035], n=3504 |
| 2+Gol | SOSTITUISCE (griglia implicita) | Δ 0,0022 [0,0011; 0,0033], n=3504 |

Mercati in cui la griglia implicita sostituisce il modello: **20** su 20. Per gli altri: nessuna differenza dimostrata, oppure modello migliore dimostrato (vedi colonna).

## 7. Sensibilita': Pinnacle di chiusura (sottocampione)

Stessa regola, con griglia implicita da Pinnacle di chiusura, su **2623** partite con quote complete. Non cambia la conclusione principale: e' informativa.

| mercato | n | Brier griglia (Pin. ch.) | Brier modello | Δ [IC 95%] | esito |
|---|---|---|---|---|---|
| 1 | 2623 | 0,2044 | 0,2168 | 0,0124 [0,0088; 0,0159] | SOSTITUISCE (griglia implicita) |
| X | 2623 | 0,1855 | 0,1877 | 0,0022 [0,0007; 0,0039] | SOSTITUISCE (griglia implicita) |
| 2 | 2623 | 0,1849 | 0,1947 | 0,0098 [0,0062; 0,0134] | SOSTITUISCE (griglia implicita) |
| 1X | 2623 | 0,1849 | 0,1947 | 0,0098 [0,0063; 0,0134] | SOSTITUISCE (griglia implicita) |
| X2 | 2623 | 0,2044 | 0,2168 | 0,0124 [0,0089; 0,0161] | SOSTITUISCE (griglia implicita) |
| 12 | 2623 | 0,1855 | 0,1877 | 0,0022 [0,0007; 0,0038] | SOSTITUISCE (griglia implicita) |
| Over 1.5 | 2623 | 0,1719 | 0,1763 | 0,0044 [0,0029; 0,0060] | SOSTITUISCE (griglia implicita) |
| Under 1.5 | 2623 | 0,1719 | 0,1763 | 0,0044 [0,0028; 0,0060] | SOSTITUISCE (griglia implicita) |
| Over 2.5 | 2623 | 0,2388 | 0,2459 | 0,0071 [0,0045; 0,0097] | SOSTITUISCE (griglia implicita) |
| Under 2.5 | 2623 | 0,2388 | 0,2459 | 0,0071 [0,0043; 0,0098] | SOSTITUISCE (griglia implicita) |
| Over 3.5 | 2623 | 0,2019 | 0,2067 | 0,0048 [0,0024; 0,0071] | SOSTITUISCE (griglia implicita) |
| Under 3.5 | 2623 | 0,2019 | 0,2067 | 0,0048 [0,0023; 0,0071] | SOSTITUISCE (griglia implicita) |
| Gol | 2623 | 0,2456 | 0,2492 | 0,0036 [0,0015; 0,0056] | SOSTITUISCE (griglia implicita) |
| No Gol | 2623 | 0,2456 | 0,2492 | 0,0036 [0,0015; 0,0056] | SOSTITUISCE (griglia implicita) |
| 1+Over 1.5 | 2623 | 0,1883 | 0,2009 | 0,0126 [0,0093; 0,0159] | SOSTITUISCE (griglia implicita) |
| 2+Over 1.5 | 2623 | 0,1630 | 0,1707 | 0,0077 [0,0050; 0,0103] | SOSTITUISCE (griglia implicita) |
| 1X+Over 1.5 | 2623 | 0,2227 | 0,2330 | 0,0103 [0,0073; 0,0131] | SOSTITUISCE (griglia implicita) |
| X2+Under 3.5 | 2623 | 0,2202 | 0,2293 | 0,0091 [0,0065; 0,0118] | SOSTITUISCE (griglia implicita) |
| 1+Gol | 2623 | 0,1520 | 0,1554 | 0,0034 [0,0018; 0,0049] | SOSTITUISCE (griglia implicita) |
| 2+Gol | 2623 | 0,1192 | 0,1220 | 0,0028 [0,0016; 0,0041] | SOSTITUISCE (griglia implicita) |

## 8. Bet365 vs Pinnacle: margine e stima della quota (sezione D)

Margine = Σ(1/quota) − 1 per libro. Fasce per **quota equa Pinnacle** (1/p depurata). Per la stima: R = q_B365 / p_depurata_Pinnacle, con p depurata proporzionale. La stima della quota bet365 e' q̂ = 1 / (p_depurata · R̂).

### 8.1 Margine per lega (partite del campione 2024/25 + 2025/26, quote anticipate)

| mercato | lega | partite | margine mediano B365 | margine mediano Pinnacle | B365 − Pinnacle (mediana) | P10 | P90 |
|---|---|---|---|---|---|---|---|
| 1X2 ant. | Bundesliga | 456 | 5,49 % | 3,49 % | 1,98 pt | 1,15 pt | 2,82 pt |
| 1X2 ant. | La Liga | 569 | 5,58 % | 3,47 % | 2,03 pt | 1,22 pt | 2,93 pt |
| 1X2 ant. | Ligue 1 | 459 | 5,52 % | 3,48 % | 1,93 pt | 1,07 pt | 2,61 pt |
| 1X2 ant. | Premier League | 590 | 5,49 % | 3,52 % | 1,94 pt | 1,13 pt | 2,73 pt |
| 1X2 ant. | Serie A | 580 | 5,49 % | 3,51 % | 1,96 pt | 1,19 pt | 2,74 pt |
| O/U 2,5 ant. | Bundesliga | 438 | 5,33 % | 3,56 % | 1,66 pt | -0,16 pt | 2,29 pt |
| O/U 2,5 ant. | La Liga | 566 | 5,33 % | 3,49 % | 1,67 pt | -0,10 pt | 2,30 pt |
| O/U 2,5 ant. | Ligue 1 | 455 | 5,33 % | 3,38 % | 1,66 pt | -0,30 pt | 2,29 pt |
| O/U 2,5 ant. | Premier League | 587 | 5,36 % | 3,52 % | 1,75 pt | 0,00 pt | 2,26 pt |
| O/U 2,5 ant. | Serie A | 579 | 5,33 % | 3,37 % | 1,77 pt | -0,25 pt | 2,23 pt |

### 8.2 Margine effettivo per fascia di quota equa (r = q_B365 / p_depurata − 1)

| tipo | fascia di quota equa | n esiti | r mediano | margine effettivo mediano |
|---|---|---|---|---|
| 1X2 | ≥5,00 | 1484 | 1,0761 | 7,61 % |
| 1X2 | 3,00-5,00 | 3587 | 1,0571 | 5,71 % |
| 1X2 | 1,50-2,00 | 933 | 1,0494 | 4,94 % |
| 1X2 | 2,00-3,00 | 1514 | 1,0566 | 5,66 % |
| 1X2 | <1,50 | 444 | 1,0438 | 4,38 % |
| O/U 2,5 | 2,00-3,00 | 2425 | 1,0551 | 5,51 % |
| O/U 2,5 | 1,50-2,00 | 2378 | 1,0443 | 4,43 % |
| O/U 2,5 | 3,00-5,00 | 224 | 1,0372 | 3,72 % |
| O/U 2,5 | <1,50 | 222 | 1,0532 | 5,32 % |
| O/U 2,5 | ≥5,00 | 1 | 1,1623 | 16,23 % |

### 8.3 Errore della stima della quota bet365 (fuori campione)

R = q_B365 / p_depurata_Pinnacle stimato in 2024/25; test sul 2025/26. Errore = quota stimata / quota reale - 1.

| modello di stima | campione | n | errore assoluto mediano (quota) | errore assoluto medio | P90 errore assoluto | errore medio con segno | errore medio in probabilita' |
|---|---|---|---|---|---|---|---|
| lega x fascia x tipo | test 2025/26 (fuori campione) | 4490 | 1,36 % | 1,99 % | 4,09 % | 0,09 % | 0,66 pt |
| lega x fascia x tipo | in campione 2024/25 | 8722 | 1,46 % | 2,15 % | 4,55 % | 0,15 % | 0,70 pt |
| fascia x tipo (senza lega) | test 2025/26 (fuori campione) | 4490 | 1,37 % | 1,99 % | 4,12 % | 0,08 % | 0,66 pt |
| fascia x tipo (senza lega) | in campione 2024/25 | 8722 | 1,48 % | 2,16 % | 4,56 % | 0,14 % | 0,70 pt |
| tipo (senza fascia) | test 2025/26 (fuori campione) | 4490 | 1,38 % | 2,06 % | 4,26 % | 0,35 % | 0,68 pt |
| tipo (senza fascia) | in campione 2024/25 | 8722 | 1,55 % | 2,27 % | 4,67 % | 0,43 % | 0,73 pt |
| costante (nessuna segmentazione) | test 2025/26 (fuori campione) | 4490 | 1,40 % | 2,08 % | 4,26 % | 0,39 % | 0,68 pt |
| costante (nessuna segmentazione) | in campione 2024/25 | 8722 | 1,55 % | 2,29 % | 4,69 % | 0,47 % | 0,73 pt |

## 9. Limiti e cosa non e' verificato

- Il fit implicito usa 1X2 e Over 2,5 B365 ANTICIPATE: sono quote 'pre' senza orario di rilevazione nel CSV; la dicitura pre-chiusura e' dichiarata, non verificata dal file.
- Quote Pinnacle: colonne PS*/P>2,5 usate come anticipate e PSC*/PC>2,5 come chiusura, per convenzione football-data; non verificato dal file quale sia apertura o chiusura per ogni campo.
- I mercati Over/Under 1,5 e 3,5 e Gol/No Gol NON sono quotati nel campione: sono ricavati dalla griglia implicita (1X2 + O/U 2,5). La loro qualita' dipende dalla forma della griglia, non da una quota diretta.
- Combinazioni (1+Over 1,5, ecc.) del modello: nessuna griglia congiunta di produzione; usata la griglia Poisson dai lambda puri della testa Totali. Non e' la griglia che produce il 1X2 del modello: confronto con un'approssimazione dichiarata.
- Il bootstrap usa la data come giornata (il CSV non ha la giornata): i blocchi possono essere piu' fini della giornata reale per turni spezzati su piu' date.
- Il Brier non e' pesato per quota: non dice nulla sul valore economico (EV) di una giocata. Questo referto valuta la probabilita', non il profitto.
- Nessun replay del Registro, nessuna scrittura: le probabilita' di topmix_mercato_v3 non sono state rigenerate in questo referto.

## 10. Libreria penaltyblog (sezione A)

- **Versione e installazione**: penaltyblog 1.13.1 da PyPI su Python 3.11.2 (installazione riuscita nel venv dedicato). Un `pip install --dry-run` nel venv di audit (con SoccerMath/requirements.txt e requirements-audit.txt) non cambia numpy, pandas o scipy: aggiunge una cinquantina di pacchetti.
- **Dipendenze dirette** (22): beautifulsoup4, cssselect, cython, fsspec, html5lib, ipywidgets, kaleido, lxml, matplotlib, networkx, numpy, orjson, pandas, plotly, pulp, requests, scipy, socks, statsbombpy, tabulate, tqdm, wrapper-tls-requests. Sono pesanti (matplotlib, plotly, kaleido, statsbombpy, ipywidgets). **Non compatibile come dipendenza di produzione** (SoccerMath/requirements.txt, Streamlit Cloud): non verificato su Streamlit Cloud, ma la sola mole delle dipendenze lo sconsiglia.
- **Funzione**: `penaltyblog.models.goal_expectancy_extended` (NON in `penaltyblog.implied`). Minimizza il Brier su 5 probabilita' (1X2 + O/U 2,5) con 3 parametri (log mu casa, log mu trasferta, rho). Non e' un risolutore esatto: il residuo va misurato.
- **Fit su 3504 partite** (B365 1X2 + O/U 2,5 completi): riusciti e riproducono le quote (residuo ≤ 1e-3): **3483**; NON riproducono le quote: **21** (residuo massimo 0,298), con `success = True` nel dizionario di output. Sintomo: lambda/mu al bordo exp(3) ≈ 20,1 e rho al bordo 0,5 (partite con lambda o mu al bordo: 16). Il fit scipy di audit riproduce le stesse quote con residuo massimo 1.47e-12.
- **Parametri sulle partite riuscite** (scarto assoluto rispetto al fit scipy): lambda mediano 0,005 (p95 0,019), mu mediano 0,007 (p95 0,030), rho mediano 3.376e-04 (p95 0,003). Gli scarti non sono zero: vedi il punto sulla convenzione.
- **Convenzione tau di `create_dixon_coles_grid`** su 200 casi (fuori dai limiti di penaltyblog: 0): scarto massimo cella per cella rispetto a `dc_matrix` (produzione) 0,029; escludendo le celle (0,1) e (1,0) scende a 0,0022 (residuo dovuto alla rinormalizzazione della griglia); rispetto alla convenzione SCAMBIATA (0,1) *= 1+mu·rho, (1,0) *= 1+lambda·rho lo scarto e' 8.33e-17. Conclusione: penaltyblog usa lambda e mu invertiti sulle due celle a un gol, rispetto alla convenzione di produzione (`models/dixon_coles.tau_correction`).
- **Coerenza interna** di penaltyblog (sua griglia con i suoi parametri vs le quote di partenza, 300 casi): residuo massimo 8.127e-05.
- **Tempi** (3504 fit): penaltyblog 158.9 s, scipy 71.3 s.
- **Decisione**: penaltyblog NON si usa per il referto. Motivi: (1) dipendenze pesanti e non necessarie; (2) convenzione tau diversa da quella di produzione; (3) fallimenti silenziosi su circa lo 0,6% delle partite. Il referto usa il fit scipy in `audit/griglia_core.py`, con la convenzione di produzione e il residuo riportato per partita.
