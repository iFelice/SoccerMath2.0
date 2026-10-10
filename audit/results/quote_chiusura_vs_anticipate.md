# Le quote di chiusura sono piu' informative delle quote anticipate? — referto di audit (sola lettura)

Generato da `audit/quote_chiusura_vs_anticipate.py` (nessuna modifica a `SoccerMath/`, nessun replay `--write`, nessuna chiamata all'API: dati solo dai CSV football-data in `SoccerMath/database/`). Commit di base: `f263700fdce93bf5ea7c807db02c8d737b5a55f6`. Bootstrap: 2000 repliche a blocchi (lega x stagione x giornata), seme 20261008 (stesso della PR #49). Tempo di esecuzione: 5 s.
Comando: `python audit/quote_chiusura_vs_anticipate.py`.

## 0. Regole dichiarate (fissate prima di guardare i risultati)

- De-vig PROPORZIONALE per tutte le fonti; terna valida = tre quote presenti e > 1.0.
- Campione: solo partite con terna anticipata E terna di chiusura della fonte in esame; si dichiara quante restano.
- Metriche su tutte le partite del campione: Brier 1X2 e LogLoss per anticipata e chiusura.
- Top Mix (esito piu' probabile con p >= 0,55): n, hit rate, confidenza media dichiarata, per anticipata e chiusura.
- Delta Brier = Brier(chiusura) − Brier(anticipata) con bootstrap a blocchi (lega x stagione x giornata, 2000 repliche) e IC 95% percentile.
- REGOLA DI DECISIONE: la chiusura e' 'piu' informativa' se l'IC 95% di Delta Brier esclude lo zero a suo favore (IC interamente negativo); altrimenti 'nessuna differenza dimostrata'.
- Movimenti: Delta = p_chiusura − p_anticipata sull'esito favorito secondo l'anticipata (punti percentuali). Fasce: F1: Delta <= −5; F2: −5 < Delta <= −2; F3: −2 < Delta < +2; F4: +2 <= Delta < +5; F5: Delta >= +5.

## 1. Copertura delle colonne e campione

| Lega | Stagione | Righe | B365H | B365D | B365A | PSH | PSD | PSA | B365CH | B365CD | B365CA | PSCH | PSCD | PSCA | Terna B365 pre | Terna Pin pre | Terna B365 close | Terna Pin close |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Serie A | 2024/25 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 |
| Serie A | 2025/26 | 380 | 380 | 380 | 380 | 200 | 200 | 200 | 380 | 380 | 380 | 198 | 198 | 198 | 380 | 200 | 380 | 198 |
| Premier League | 2024/25 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 |
| Premier League | 2025/26 | 380 | 380 | 380 | 380 | 210 | 210 | 210 | 380 | 380 | 380 | 210 | 210 | 210 | 380 | 210 | 380 | 210 |
| La Liga | 2024/25 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 | 380 |
| La Liga | 2025/26 | 380 | 380 | 380 | 380 | 189 | 189 | 189 | 380 | 380 | 380 | 188 | 188 | 188 | 380 | 189 | 380 | 188 |
| Bundesliga | 2024/25 | 306 | 306 | 306 | 306 | 306 | 306 | 306 | 306 | 306 | 306 | 306 | 306 | 306 | 306 | 306 | 306 | 306 |
| Bundesliga | 2025/26 | 306 | 306 | 306 | 306 | 150 | 150 | 150 | 306 | 306 | 306 | 149 | 149 | 149 | 306 | 150 | 306 | 149 |
| Ligue 1 | 2024/25 | 306 | 306 | 306 | 306 | 306 | 306 | 306 | 306 | 306 | 306 | 306 | 306 | 306 | 306 | 306 | 306 | 306 |
| Ligue 1 | 2025/26 | 306 | 306 | 306 | 306 | 153 | 153 | 153 | 306 | 306 | 306 | 153 | 153 | 153 | 306 | 153 | 306 | 153 |

| Campione | Partite |
|---|---|
| Righe totali 2024/25 + 2025/26 (5 leghe) | 3504 |
| Senza terna B365 anticipata | 0 |
| Senza terna B365 chiusura | 0 |
| **Campione comune B365** (pre E chiusura B365 valide) — campione principale | **3504** |
| Campione Pinnacle a fonte uguale (pre E chiusura Pinnacle valide) — controllo | 2650 |

L'esito e' preso da FTR; nella PR #49 FTR coincide con l'esito dai gol in ogni riga del campione.

## 2. Metriche su tutte le partite (Brier 1X2 e LogLoss)

Valori piu' bassi = meglio. Campione comune B365 (tutte le partite con entrambe le fonti):

| Fonte | n | Brier 1X2 | LogLoss |
|---|---|---|---|
| B365 anticipata (de-vig prop.) | 3504 | 0.5781 | 0.9719 |
| B365 chiusura (de-vig prop.) | 3504 | 0.5769 | 0.9700 |

Per stagione:

| Stagione | n | Brier anticipata | Brier chiusura | LogLoss anticipata | LogLoss chiusura |
|---|---|---|---|---|---|
| 2024/25 | 1752 | 0.5734 | 0.5714 | 0.9647 | 0.9620 |
| 2025/26 | 1752 | 0.5827 | 0.5823 | 0.9790 | 0.9779 |

Controllo a fonte uguale, campione Pinnacle (pre E chiusura Pinnacle valide):

| Fonte | n | Brier 1X2 | LogLoss |
|---|---|---|---|
| Pinnacle anticipata (de-vig prop.) | 2650 | 0.5727 | 0.9633 |
| Pinnacle chiusura (de-vig prop.) | 2650 | 0.5716 | 0.9618 |

Per stagione:

| Stagione | n | Brier anticipata | Brier chiusura | LogLoss anticipata | LogLoss chiusura |
|---|---|---|---|---|---|
| 2024/25 | 1752 | 0.5728 | 0.5706 | 0.9635 | 0.9606 |
| 2025/26 | 898 | 0.5725 | 0.5736 | 0.9628 | 0.9641 |

## 3. Top Mix (esito piu' probabile, p >= 0,55)

IC 95% bootstrap a blocchi (stessi blocchi, 2000 repliche).

| Campione | Fonte | Scelte (n) | Hit rate [IC 95%] | Confidenza media [IC 95%] |
|---|---|---|---|---|
| B365 (campione comune) | anticipata | 1302 | 0.6751 [0.6501; 0.7007] | 0.6563 [0.6523; 0.6601] |
| B365 (campione comune) | chiusura | 1297 | 0.6762 [0.6493; 0.7020] | 0.6580 [0.6539; 0.6623] |
| Pinnacle (a fonte uguale) | anticipata | 1019 | 0.6850 [0.6571; 0.7141] | 0.6620 [0.6574; 0.6664] |
| Pinnacle (a fonte uguale) | chiusura | 1002 | 0.6896 [0.6602; 0.7184] | 0.6668 [0.6619; 0.6718] |

Per stagione (n ammesse e confidenza media dichiarata):

| Campione | Stagione | Fonte | Scelte (n) | Confidenza media |
|---|---|---|---|---|
| B365 (campione comune) | 2024/25 | anticipata | 689 di 1752 | 0.6581 |
| B365 (campione comune) | 2024/25 | chiusura | 688 di 1752 | 0.6613 |
| B365 (campione comune) | 2025/26 | anticipata | 613 di 1752 | 0.6543 |
| B365 (campione comune) | 2025/26 | chiusura | 609 di 1752 | 0.6543 |
| Pinnacle (a fonte uguale) | 2024/25 | anticipata | 707 di 1752 | 0.6624 |
| Pinnacle (a fonte uguale) | 2024/25 | chiusura | 696 di 1752 | 0.6685 |
| Pinnacle (a fonte uguale) | 2025/26 | anticipata | 312 di 898 | 0.6610 |
| Pinnacle (a fonte uguale) | 2025/26 | chiusura | 306 di 898 | 0.6630 |

## 4. Delta Brier (chiusura − anticipata) e regola di decisione

Delta negativo = la chiusura e' migliore (Brier piu' basso). IC 95% bootstrap a blocchi.

| Confronto | n | Delta Brier [IC 95%] |
|---|---|---|
| B365 — pooled | 3504 | -0.0012 [-0.0028; 0.0004] |
| B365 — Serie A | 760 | -0.0007 [-0.0040; 0.0026] |
| B365 — Premier League | 760 | -0.0031 [-0.0065; 0.0003] |
| B365 — La Liga | 760 | -0.0018 [-0.0051; 0.0017] |
| B365 — Bundesliga | 612 | 0.0003 [-0.0033; 0.0038] |
| B365 — Ligue 1 | 612 | -0.0001 [-0.0045; 0.0043] |
| B365 — 2024/25 | 1752 | -0.0019 [-0.0042; 0.0003] |
| B365 — 2025/26 | 1752 | -0.0004 [-0.0025; 0.0017] |
| Pinnacle — pooled | 2650 | -0.0011 [-0.0029; 0.0008] |
| Pinnacle — Serie A | 578 | 0.0009 [-0.0025; 0.0045] |
| Pinnacle — Premier League | 590 | -0.0026 [-0.0065; 0.0008] |
| Pinnacle — La Liga | 568 | -0.0020 [-0.0058; 0.0018] |
| Pinnacle — Bundesliga | 455 | -0.0013 [-0.0058; 0.0033] |
| Pinnacle — Ligue 1 | 459 | -0.0002 [-0.0057; 0.0047] |

Applicazione della regola dichiarata:
- **B365 (campione comune, decisione principale):** Delta Brier pooled = -0.0012 [-0.0028; 0.0004] → **NESSUNA DIFFERENZA DIMOSTRATA**.
- Pinnacle (a fonte uguale, controllo): Delta Brier pooled = -0.0011 [-0.0029; 0.0008] → nessuna differenza dimostrata.

## 5. Analisi dei movimenti (Delta = p_chiusura − p_anticipata sul favorito)

Favorito = esito piu' probabile secondo la quota anticipata. Delta in punti percentuali.

| Statistica | Valore |
|---|---|
| n | 3504 |
| media | -0.20 pt |
| mediana | -0.09 pt |
| deviazione std | 3.16 pt |
| min / max | -12.90 / +14.70 pt |
| quantili 5/10/25/75/90/95 | -5.51 / -4.17 / -2.22 / +1.81 / +3.74 / +4.93 pt |
| share |Delta| < 1 pt | 27.7% |
| share |Delta| < 2 pt | 50.1% |
| share |Delta| >= 2 pt | 49.9% |
| share |Delta| >= 5 pt | 11.2% |
| hit rate del favorito (tutte le partite) | 0.5337 |

Fasce di Delta (B365, campione comune):

| Fascia | n | Hit rate favorito | Prob media anticipata | Prob media chiusura | Hit − anticipata | Hit − chiusura | Delta medio |
|---|---|---|---|---|---|---|---|
| F1: Delta <= -5 | 223 | 0.4619 | 0.5252 | 0.4583 | -0.0633 | +0.0036 | -6.69 pt |
| F2: -5 < Delta <= -2 | 733 | 0.5252 | 0.5187 | 0.4868 | +0.0065 | +0.0384 | -3.19 pt |
| F3: -2 < Delta < +2 | 1754 | 0.5376 | 0.5283 | 0.5285 | +0.0093 | +0.0091 | +0.02 pt |
| F4: +2 <= Delta < +5 | 626 | 0.5463 | 0.5205 | 0.5526 | +0.0258 | -0.0063 | +3.21 pt |
| F5: Delta >= +5 | 168 | 0.5774 | 0.5008 | 0.5665 | +0.0766 | +0.0109 | +6.57 pt |

Controllo a fonte uguale (Pinnacle, campione Pinnacle):

| Fascia | n | Hit rate favorito | Prob media anticipata | Prob media chiusura | Hit − anticipata | Hit − chiusura |
|---|---|---|---|---|---|---|
| F1: Delta <= -5 | 161 | 0.4224 | 0.5174 | 0.4501 | -0.0951 | -0.0278 |
| F2: -5 < Delta <= -2 | 463 | 0.5443 | 0.5264 | 0.4947 | +0.0179 | +0.0496 |
| F3: -2 < Delta < +2 | 1419 | 0.5384 | 0.5298 | 0.5299 | +0.0086 | +0.0085 |
| F4: +2 <= Delta < +5 | 489 | 0.5501 | 0.5263 | 0.5581 | +0.0238 | -0.0080 |
| F5: Delta >= +5 | 118 | 0.6017 | 0.5262 | 0.5918 | +0.0755 | +0.0099 |

Aggregati per la domanda (B365, campione comune):

| Gruppo | n | Hit rate | Prob media anticipata | Prob media chiusura | Hit − anticipata | Hit − chiusura |
|---|---|---|---|---|---|---|
| accorcia (Delta >= +2 pt) | 794 | 0.5529 | 0.5163 | 0.5556 | +0.0366 | -0.0027 |
| allunga (Delta <= −2 pt) | 956 | 0.5105 | 0.5202 | 0.4802 | -0.0098 | +0.0303 |

## 6. Conclusione e implicazioni per l'orario del giro quote

**Secondo la regola dichiarata, NESSUNA DIFFERENZA DIMOSTRATA:** Delta Brier pooled = -0.0012, IC 95% [-0.0028; 0.0004] (contiene lo zero); campione 3504 partite. Lo scarto e' piccolo anche in valore assoluto (0.12 punti percentuali di Brier).
Il controllo a fonte uguale (Pinnacle pre vs chiusura, n=2650) da: Delta Brier = -0.0011 [-0.0029; 0.0008].
Quando il favorito si ACCORCIA (Delta >= +2 pt; n=794, 23% delle partite): hit rate 0.5529 vs probabilità media anticipata 0.5163 (scarto +0.0366) → il favorito vince PIU' spesso di quanto dicesse la quota anticipata. Ma rispetto alla probabilità dichiarata in chiusura (0.5556) lo scarto e' solo -0.0027: la chiusura ha gia' assorbito il movimento.
Quando il favorito si ALLUNGA (Delta <= −2 pt; n=956, 27% delle partite): hit rate 0.5105 vs probabilità media anticipata 0.5202 (scarto -0.0098) → il favorito vince MENO spesso di quanto dicesse la quota anticipata. Rispetto alla chiusura (0.4802) lo scarto e' +0.0303: su questo campione la chiusura corregge leggermente piu' del necessario.
Il pattern e' monotono: lo scarto (hit rate − probabilità anticipata) cresce con Delta da -0.0633 (favorevole che si allunga di >= 5 pt) a +0.0766 (favorevole che si accorcia di >= 5 pt): piu' il favorito si accorcia in chiusura, piu' l'anticipata sottostimava la sua frequenza di vittoria reale.
Nelle fasce estreme l'effetto e' netto e monocausale: favorito che si allunga di >= 5 pt (n=223): hit 0.4619 vs anticipata 0.5252 (-0.0633) ma quasi calibrato sulla chiusura (+0.0036); favorito che si accorcia di >= 5 pt (n=168): hit 0.5774 vs anticipata 0.5008 (+0.0766) e quasi calibrato sulla chiusura (+0.0109). L'informazione esiste, e sta nel movimento; la chiusura la riconcilia, l'anticipata no.
I movimenti grandi non sono poi cosi' rari da essere irrilevanti: 50% delle partite si muovono di 2 pt o piu' sul favorito e |Delta| >= 5 pt tocca il 11.2%; ma sul totale il Delta Brier resta dentro il rumore (IC che contiene lo zero).
**Implicazioni per l'orario del giro quote (piano 500 crediti/mese, 1 giro = 5 crediti).** Il budget regge 100 gironi/mese, cioe' ~3 gironi/giorno. Lo scenario attuale (1 giro/giorno, cron 08:17 UTC) costa 5 crediti/giorno = 140–155 crediti in un mese di 28–31 giorni: ~3/4 del budget con un solo giro, e il secondo tentativo (10:47 UTC) costa gia' 0 quando il primo e' fresco.
La chiusura non dimostra un vantaggio significativo sull'anticipata: **non conviene aggiungere gironi di routine per 'catturare' la chiusura** — il giro unico mattutino resta la scelta dominante per rapporto informazione/costo. Il margine di budget (~345 crediti/mese, ~69 gironi) va tenuto per i cron saltati (gia' coperti a costo zero dalla guardia di freschezza) e per gironi manuali mirati (es. sabato 15:00–17:00 UTC) su partite in cui interessa un movimento specifico, non per la routine giornaliera. Se in futuro l'app sfruttera' il movimento stesso (Delta) come segnale, il dato di questo audit dice che vale solo per movimenti >= 2 pt, cioe' per ~la meta' delle giornate: un giro pomeridiano mirato a quelle partite sarebbe il candidato naturale, non il giro di chiusura.

## 7. Limiti dichiarati

- Cross-verifica con la PR #49: su questo campione i valori di Brier, LogLoss, Top Mix e Delta Brier (pooled e per lega) riportati in questo referto riproducono quelli del referto `audit/results/onex2_market_test.md` (stesso campione, stesso de-vig proporzionale, stesso seme); le novita' sono la coppia Pinnacle a fonte uguale e l'analisi dei movimenti.
- L'orario di rilevazione delle colonne del CSV non e' nel file: 'anticipata' e 'chiusura' sono le diciture della fonte football-data (B365 pre = commessa della PR #49; B365C e PSCH = chiusura di mercato).
- Il campione Pinnacle e' un sottoinsieme: la chiusura Pinnacle e' mancante su parte del 2025/26, quindi il controllo a fonte uguale non e' sullo stesso campione del confronto principale.
- Il de-vig proporzionale presuppone che il margine sia distribuito proporzionalmente agli esiti; e' la decisione gia' usata nella PR #49 e qui non viene rivisitata.
- Il bootstrap a blocchi tratta la giornata come unita'; le partite della stessa giornata condividono squadre.
- Nessun dato live dell'app e' stato usato: e' un esperimento retrospettivo su CSV, non una stima del valore di un giro quote in orario specifico.
