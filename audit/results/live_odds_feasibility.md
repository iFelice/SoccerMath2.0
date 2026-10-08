# Fattibilita' di una fonte di quote 1X2 dal vivo — referto di audit (sola lettura)

Generato da `audit/live_odds_feasibility.py` (2026-10-08T23:59:41Z), branch `arena/edb67158-soccermath2-0`, commit `2c261cf`. Nessuna modifica a `SoccerMath/`: tutti i file nuovi vivono in `audit/`.

Comandi:

```
python audit/bookmaker_source_test.py      # punto 1 (quale bookmaker basta)
python audit/live_odds_probe.py --out audit/data/live_odds_probe   # punto 2 (rete)
python audit/live_odds_match.py            # punto 3 (abbinamento nomi)
python audit/live_odds_feasibility.py      # questo referto (punti 1-5)
```

## 0. Prerequisiti

| Voce | Esito | Comando / link | Evidenza |
|---|---|---|---|
| Branch partito da main dopo il merge della PR #49 | OK | git log --oneline -1; gh pr view 49 --json mergedAt | HEAD = 2c261cf; PR #49 mergiata il 2026-10-08T22:55:04Z (merge commit f77366b) |
| Diff vuoto all'inizio del lavoro | OK | git diff --name-only origin/main...HEAD | nessun file (branch allineato a main: 0 commit avanti, 0 indietro) |
| Script della PR #49 presente | OK | ls -l audit/onex2_market_test.py | 68.666 byte; `python -m pytest audit/test_onex2_market_test.py`: 18 test verdi |
| Secret ODDS_API_KEY esistente nel repository | OK | workflow temporaneo: ${{ secrets.ODDS_API_KEY != '' }} | SECRET_PRESENT = true; 6 chiamate su 6 hanno risposto HTTP 200 (con chiave assente o errata: 401) |
| Valore del secret leggibile dall'agente | NON VERIFICABILE | gh secret list | HTTP 403 Resource not accessible by integration: il token non ha il permesso sui secret. Il valore non e' stato letto ne' copiato da nessuna parte |

## 1. Quale bookmaker basta (dati storici gia' presenti)

Stesso protocollo della PR #49 (funzioni riusate, non riscritte): stagioni 2024/25 e 2025/26, de-vig proporzionale (decisione) e Shin (sensibilita'), LogLoss/Brier/RPS, BSS contro il base rate del train, reliability/resolution a 10 bin, regola Top Mix (esito piu' probabile se >= 0,55), bootstrap a blocchi (lega x stagione x giornata) con 2000 repliche e seme 20261008. Referto completo: `audit/results/bookmaker_source_test.md`.

Campioni: comune (B365+Avg+Max validi) = 3504; di cui con Pinnacle pre valido = 2654; righe totali delle due stagioni = 3504.

### 1a. Qualita' e scelte Top Mix (campione comune)

| Fonte | n | LogLoss | Brier | RPS | BSS LogLoss | Scelte Top Mix | Hit rate | Conf − hit |
|---|---|---|---|---|---|---|---|---|
| Bet365 pre-chiusura (de-vig prop.) — RIFERIMENTO | 3504 | 0.9719 | 0.5781 | 0.1962 | 0.0967 | 1302 | 0.6751 | -0.0188 |
| Media di mercato Avg (de-vig prop.) | 3504 | 0.9712 | 0.5778 | 0.1961 | 0.0974 | 1298 | 0.6780 | -0.0199 |
| Massimo di mercato Max (de-vig prop.) | 3504 | 0.9705 | 0.5775 | 0.1960 | 0.0980 | 1342 | 0.6714 | -0.0085 |
| Pinnacle (de-vig prop.) | 2654 | 0.9634 | 0.5728 | 0.1938 | 0.1050 | 1019 | 0.6850 | -0.0230 |
| Consenso: media delle prob. de-vigate dei singoli book | 2833 | 0.9725 | 0.5787 | 0.1956 | 0.0944 | 1040 | 0.6779 | -0.0227 |
| Betfred (de-vig prop.) | 1747 | 0.9781 | 0.5824 | 0.1977 | 0.0875 | 606 | 0.6766 | -0.0201 |
| BetMGM (de-vig prop.) | 1742 | 0.9772 | 0.5819 | 0.1976 | 0.0882 | 627 | 0.6715 | -0.0133 |
| BetVictor (de-vig prop.) | 1742 | 0.9780 | 0.5823 | 0.1978 | 0.0875 | 604 | 0.6887 | -0.0332 |
| Bet&Win / bwin (de-vig prop.) | 2837 | 0.9739 | 0.5796 | 0.1959 | 0.0932 | 1005 | 0.6836 | -0.0289 |
| Coral (de-vig prop.) | 1280 | 0.9727 | 0.5790 | 0.1950 | 0.0910 | 422 | 0.6991 | -0.0434 |
| Ladbrokes (de-vig prop.) | 1309 | 0.9766 | 0.5818 | 0.1963 | 0.0879 | 437 | 0.6911 | -0.0379 |
| Bet365 pre-chiusura (de-vig Shin) | 3504 | 0.9712 | 0.5777 | 0.1960 | 0.0974 | 1407 | 0.6645 | -0.0033 |
| Media di mercato Avg (de-vig Shin) | 3504 | 0.9705 | 0.5775 | 0.1960 | 0.0980 | 1376 | 0.6708 | -0.0061 |
| Pinnacle (de-vig Shin) | 2654 | 0.9628 | 0.5725 | 0.1937 | 0.1056 | 1055 | 0.6787 | -0.0112 |
| Consenso (de-vig Shin) | 2833 | 0.9718 | 0.5784 | 0.1954 | 0.0951 | 1102 | 0.6724 | -0.0106 |
| Bet365 chiusura (contesto, de-vig prop.) | 3504 | 0.9700 | 0.5769 | 0.1957 | 0.0985 | 1297 | 0.6762 | -0.0182 |
| Pinnacle chiusura (contesto, de-vig prop.) | 2650 | 0.9618 | 0.5716 | 0.1935 | 0.1063 | 1002 | 0.6896 | -0.0228 |
| Betfair Exchange (senza commissione, de-vig prop.) | 3397 | 0.9701 | 0.5771 | 0.1961 | 0.0983 | 1337 | 0.6687 | -0.0039 |

### 1b. Differenze appaiate contro Bet365 (A − B365), IC 95% bootstrap

Delta negativo = A migliore di B365. L'hit rate e' appaiato sulle partite ammesse da ENTRAMBE le fonti: il valore e' 0 per tutte le fonti perche' la scelta ammessa coincide sempre con quella di B365 (nessuna divergenza di esito sulle partite a soglia).

| Fonte (A) | n confronto | Δ LogLoss [IC] | Δ Brier | Δ RPS | Δ hit rate appaiato (n) |
|---|---|---|---|---|---|
| Media di mercato Avg (de-vig prop.) | 3504 | -0.0007 [-0.0014; -0.0000] | -0.0002 | -0.0001 | +0.0000 [+0.0000; +0.0000] (n=1278) |
| Massimo di mercato Max (de-vig prop.) | 3504 | -0.0014 [-0.0023; -0.0005] | -0.0005 | -0.0002 | +0.0000 [+0.0000; +0.0000] (n=1287) |
| Pinnacle (de-vig prop.) | 2654 | -0.0009 [-0.0019; -0.0000] | -0.0004 | -0.0002 | +0.0000 [+0.0000; +0.0000] (n=984) |
| Consenso: media delle prob. de-vigate dei singoli book | 2833 | -0.0003 [-0.0010; +0.0004] | -0.0001 | -0.0000 | +0.0000 [+0.0000; +0.0000] (n=1022) |
| Betfred (de-vig prop.) | 1747 | -0.0009 [-0.0024; +0.0005] | -0.0004 | -0.0001 | +0.0000 [+0.0000; +0.0000] (n=592) |
| BetMGM (de-vig prop.) | 1742 | -0.0013 [-0.0029; +0.0004] | -0.0005 | -0.0002 | +0.0000 [+0.0000; +0.0000] (n=596) |
| BetVictor (de-vig prop.) | 1742 | -0.0005 [-0.0018; +0.0009] | -0.0000 | +0.0000 | +0.0000 [+0.0000; +0.0000] (n=594) |
| Bet&Win / bwin (de-vig prop.) | 2837 | +0.0009 [-0.0002; +0.0020] | +0.0006 | +0.0003 | +0.0000 [+0.0000; +0.0000] (n=990) |
| Coral (de-vig prop.) | 1280 | +0.0002 [-0.0014; +0.0018] | +0.0001 | +0.0001 | +0.0000 [+0.0000; +0.0000] (n=416) |
| Ladbrokes (de-vig prop.) | 1309 | +0.0003 [-0.0014; +0.0020] | +0.0002 | +0.0001 | +0.0000 [+0.0000; +0.0000] (n=430) |
| Bet365 pre-chiusura (de-vig Shin) | 3504 | -0.0007 [-0.0014; +0.0000] | -0.0003 | -0.0002 | +0.0000 [+0.0000; +0.0000] (n=1302) |
| Media di mercato Avg (de-vig Shin) | 3504 | -0.0013 [-0.0023; -0.0003] | -0.0005 | -0.0002 | +0.0000 [+0.0000; +0.0000] (n=1300) |
| Pinnacle (de-vig Shin) | 2654 | -0.0016 [-0.0028; -0.0003] | -0.0007 | -0.0003 | +0.0000 [+0.0000; +0.0000] (n=988) |
| Consenso (de-vig Shin) | 2833 | -0.0010 [-0.0020; -0.0000] | -0.0004 | -0.0002 | +0.0000 [+0.0000; +0.0000] (n=1039) |
| Bet365 chiusura (contesto, de-vig prop.) | 3504 | -0.0019 [-0.0043; +0.0006] | -0.0012 | -0.0005 | +0.0000 [+0.0000; +0.0000] (n=1197) |
| Pinnacle chiusura (contesto, de-vig prop.) | 2650 | -0.0024 [-0.0053; +0.0004] | -0.0014 | -0.0005 | +0.0000 [+0.0000; +0.0000] (n=917) |
| Betfair Exchange (senza commissione, de-vig prop.) | 3397 | -0.0013 [-0.0024; -0.0003] | -0.0005 | -0.0002 | +0.0000 [+0.0000; +0.0000] (n=1264) |

### 1c. Verdetto (regola fissata prima dei numeri: C1 e C2 e C3)

| Fonte | Esito | C1 (Δ LogLoss) | C2 (Δ hit rate) | C3 (calibrazione) |
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

Criteri non soddisfatti (generati dai numeri):

- C3 non soddisfatto: scarto di calibrazione -0.0289 IC [-0.0554; -0.0013] (non contiene lo zero)

**Risposta al punto 1.** Una quota media de-vigata (`Avg`), il massimo di mercato (`Max`) e Pinnacle sono statisticamente indistinguibili da Bet365 sul campione comune: |Δ LogLoss| <= 0,0015 e le scelte ammesse dal Top Mix coincidono con quelle di Bet365. La fonte dal vivo **non ha bisogno di Bet365**: contano la copertura e la puntualita', non il marchio.

Avvertenze misurate: (a) nella stagione in corso la copertura di Pinnacle nei CSV e' 2654 righe su 3504; (b) Bet&Win/bwin e Coral hanno lo scarto di calibrazione con IC che non contiene lo zero, ma con poche scelte (1.005 e 422): e' un segnale debole, non una certezza.

### 1d. I book dei CSV sono disponibili nella fonte dal vivo candidata?

| Colonna CSV | Tornato da The Odds API (eu,uk) | Chiavi trovate |
|---|---|---|
| B365 | NO | — |
| BFD | sì | betfred_uk |
| BMGM | NO | — |
| BV | sì | betvictor |
| BW | NO | — |
| CL | sì | coral |
| LB | sì | ladbrokes_uk |
| PS | sì | pinnacle |
| BFE | sì | betfair_ex_eu, betfair_ex_uk |

## 2. Candidati dal vivo

### 2a. The Odds API — documentazione

| Voce | Valore dichiarato | Fonte ufficiale |
|---|---|---|
| Piano gratuito (Starter) | 500 crediti al mese, tutti gli sport, gran parte dei bookmaker, tutti i mercati; storico escluso. Reset il 1° del mese. | https://the-odds-api.com/ (sezione Get Access) e https://the-odds-api.com/manage/faqs.html |
| Piani a pagamento | 20.000 crediti 30 USD/mese; 100.000 crediti 59 USD/mese. | https://the-odds-api.com/ |
| Costo per chiamata (/odds) | costo = [numero di mercati] x [numero di regioni]; le risposte vuote non consumano crediti. Esempi ufficiali: 1 mercato x 3 regioni = 3; 3 mercati x 3 regioni = 9. | https://the-odds-api.com/liveapi/guides/v4/ (Usage Quota Costs) |
| Crediti residui/used/last | header di risposta x-requests-remaining, x-requests-used, x-requests-last. | https://the-odds-api.com/liveapi/guides/v4/ (Response Headers) |
| Elenco sport (/v4/sports) | gratuito: non consuma crediti. | https://the-odds-api.com/liveapi/guides/v4/ (GET sports) |
| Intervallo di aggiornamento | mercati principali (h2h/1x2): 60 s pre-partita, 40 s live; l'intervallo si riduce nelle 6 ore prima del calcio d'inizio. | https://the-odds-api.com/sports-odds-data/update-intervals.html |
| Catalogo bookmaker | l'unica chiave Bet365 e' bet365_au, regione AU, solo piani a pagamento e solo AFL/NRL. | https://the-odds-api.com/sports-odds-data/bookmaker-apis.html |
| football-data.co.uk fixture | file delle partite in programma con quote; 'le quote sono raccolte per le partite del weekend il venerdi' pomeriggio, di norma non oltre le 17:00 ora britannica; per i turni infrasettimanali il martedi' non oltre le 13:00'. | https://www.football-data.co.uk/matches.php |

### 2b. The Odds API — chiamate reali (una per lega)

Chiavi delle 5 leghe, mercato `h2h`, regioni `eu,uk`, `oddsFormat=decimal`. Snapshot: `audit/data/live_odds_probe/probe_summary.json` (2026-10-08T23:30:38Z). Il secret esiste: `SECRET_PRESENT=true` e le chiamate hanno risposto 200 (un secret assente o non valido avrebbe dato 401).

| Lega | Sport key | Chiamata | Eventi | Bookmaker | Pinnacle | Bet365 | Crediti (header) |
|---|---|---|---|---|---|---|---|
| Serie A | soccer_italy_serie_a | OK | 20 | 40 | sì | **NO** | used 33 · last 2 · remaining 467 |
| Premier League | soccer_epl | OK | 20 | 41 | sì | **NO** | used 35 · last 2 · remaining 465 |
| La Liga | soccer_spain_la_liga | OK | 20 | 37 | sì | **NO** | used 37 · last 2 · remaining 463 |
| Bundesliga | soccer_germany_bundesliga | OK | 18 | 39 | sì | **NO** | used 39 · last 2 · remaining 461 |
| Ligue 1 | soccer_france_ligue_one | OK | 18 | 37 | sì | **NO** | used 41 · last 2 · remaining 459 |

Orizzonte coperto: dal 2026-10-09T18:30:00Z al 2026-10-19T19:00:00Z (una chiamata per lega restituisce circa due giornate). Aggiornamento dei libri rilevato: da 2026-10-08T23:24:27Z a 2026-10-08T23:30:38Z: l'aggiornamento piu' vecchio fra i libri risale a 6.2 minuti prima della chiamata, il piu' recente a 0.0 minuti (chiamate scaricate alle 2026-10-08T23:30:38Z).

**Controllo Bet365.** Chiamata esplicita `bookmakers=bet365` sulla Serie A: HTTP 200, 20 eventi, bookmaker restituiti: 0. Bet365 **non e' disponibile** su queste leghe/regioni, in linea con il catalogo ufficiale (l'unica chiave Bet365 e' `bet365_au`, solo AFL/NRL e solo a pagamento).

**Controllo costo per regione.** Chiamata con `regions=eu` (una sola regione): HTTP 200, costo `x-requests-last` = 1, 22 bookmaker, Pinnacle presente. Conferma la formula documentata (costo = mercati x regioni).

### 2c. football-data.co.uk

Il file delle partite in programma esiste, in due versioni (lega principali e leghe extra), con le colonne 1X2 pre-chiusura e di chiusura di Bet365, Betfred, BetVictor, Bet&Win, Coral, Ladbrokes, Paddy Power, Sky Bet, Betfair Exchange e gli aggregati Max/Avg. Nessuna chiave richiesta.

| File | URL | HTTP | Last-Modified | Righe | Righe delle 5 leghe |
|---|---|---|---|---|---|
| fixtures_main | https://www.football-data.co.uk/fixtures.csv | OK | Fri, 02 Oct 2026 08:57:47 GMT | 46 | {'E0': 0, 'I1': 0, 'D1': 0, 'SP1': 0, 'F1': 0} |
| fixtures_extra | https://www.football-data.co.uk/new_league_fixtures.csv | OK | Tue, 06 Oct 2026 08:23:30 GMT | 16 | colonna Div assente |

**Copertura oggi.** Nel file delle leghe principali le 5 leghe del progetto (E0, I1, D1, SP1, F1) compaiono 0 volte su 46 righe: il file contiene solo E2, E3, EC, SC1, SC2, SC3, SP2 e le date vanno dal 02/10/2026 al 05/10/2026, gia' passate. Il file delle leghe extra contiene altri paesi (Brasile, ...). Con un aggiornamento settimanale dichiarato (venerdi' per il weekend, martedi' per i turni infrasettimanali) il file e' quindi inutilizzabile come fonte dal vivo per le 5 leghe: puo' restare la fonte STORICA (e' gia' quella usata dal progetto), non quella live.

### 2d. Terza fonte gratuita (al massimo una)

| Voce | Valore |
|---|---|
| Nome | OddsPapi (api.oddspapi.io) |
| Piano gratuito dichiarato | 250 richieste al mese, tutti gli sport e tutti i bookmaker, nessuna carta di credito; include Pinnacle e Bet365. |
| Fonte | https://oddspapi.io/ (piano gratuito) e https://oddspapi.io/blog/football-odds-api-soccer-data/ |
| Perche' non e' verificabile | nel repository non esiste una chiave per questo servizio (l'unica chiave quote presente e' ODDS_API_KEY, di The Odds API) e la sandbox non ha rete verso domini esterni: aprire un account richiede una casella di posta del progetto. |

### 2e. Raggiungibilita' dalla sandbox

| Prova | Esito | Comando | Evidenza |
|---|---|---|---|
| The Odds API dalla sandbox | NON OK | curl -sS -m 20 'https://api.the-odds-api.com/v4/sports/?apiKey=test' | curl: (35) OpenSSL SSL_connect: SSL_ERROR_SYSCALL (DNS risolve 65.8.54.51, connessione bloccata dal proxy della sandbox) |
| football-data.co.uk dalla sandbox | NON OK | curl -sS -m 20 https://www.football-data.co.uk/fixtures.csv | curl: (35) OpenSSL SSL_connect: SSL_ERROR_SYSCALL (DNS risolve 217.160.0.118, connessione bloccata) |
| Esecuzione delle chiamate in GitHub Actions | OK | gh workflow run zz_tmp_live_odds_probe.yml | 3 run verdi (37857450157, 37857615966, 37859819812); esito committato in audit/data/live_odds_probe/ |
| Log e artifact dei run leggibili dalla sandbox | NON OK | gh run view <id> --log; gh run download <id> | log: results-receiver.actions.githubusercontent.com bloccato; artifact: productionresultssa11.blob.core.windows.net bloccato. Per questo l'esito e' stato committato sul branch dal workflow |

## 3. Abbinamento ai nomi canonici

Nome canonico = `team_aliases.clean_name(nome dei CSV football-data)`. Insieme canonico: squadre della stagione in corso (`<Lega>_Live.csv`). Prossima giornata = regola di produzione (`app.select_next_matchday_matches`): primo kickoff futuro + finestra di `app.TOP_MIX_ROUND_WINDOW_DAYS` = 5 giorni (il filtro sul campo `matchday` non puo' essere applicato: The Odds API non lo fornisce). Nessun fuzzy matching.

| Lega | Partite prossima giornata | Abbinate con clean_name | Abbinate con il resolver di produzione | Con canonici 2025/26 + 2026/27 | Finestra |
|---|---|---|---|---|---|
| Serie A | 10 | 10 (100.0%) | 10 (100.0%) | 100.0% | 2026-10-10 → 2026-10-15 |
| Premier League | 10 | 10 (100.0%) | 10 (100.0%) | 100.0% | 2026-10-10 → 2026-10-15 |
| La Liga | 10 | 5 (50.0%) | 6 (60.0%) | 50.0% | 2026-10-09 → 2026-10-14 |
| Bundesliga | 9 | 6 (66.7%) | 7 (77.8%) | 66.7% | 2026-10-09 → 2026-10-14 |
| Ligue 1 | 9 | 8 (88.9%) | 9 (100.0%) | 88.9% | 2026-10-09 → 2026-10-14 |
| **TOTALE** | 48 | **39 (81.2%)** | **42 (87.5%)** | 81.2% | — |

**Nomi non abbinati da `clean_name`** (unici; `clean` = risultato di `clean_name`):

| Lega | Nome della fonte | clean_name | Resolver: esito | Resolver: canonico | Risolto dal resolver | Volte |
|---|---|---|---|---|---|---|
| Bundesliga | Bayer Leverkusen | Bayer Leverkusen | alias | Leverkusen | sì | 1 |
| Bundesliga | Borussia Monchengladbach | Borussia Monchengladbach | unknown | Borussia Monchengladbach | NO | 1 |
| Bundesliga | FSV Mainz 05 | FMainz 05 | unknown | FMainz 05 | NO | 1 |
| Bundesliga | Hamburger SV | Hamburger SV | alias | Hamburg | sì | 1 |
| La Liga | Atlético Madrid | Atlético Madrid | unknown | Atlético Madrid | NO | 1 |
| La Liga | CA Osasuna | CA Osasuna | unknown | CA Osasuna | NO | 1 |
| La Liga | Celta Vigo | Celta Vigo | alias | Celta | sì | 1 |
| La Liga | Deportivo La Coruña | Deportivo La Coruña | alias | Deportivo | sì | 1 |
| La Liga | Elche CF | Elche CF | unknown | Elche CF | NO | 1 |
| La Liga | Real Racing Club de Santander | Real Racing Club de Santander | unknown | Real Racing Club de Santander | NO | 1 |
| Ligue 1 | Paris Saint Germain | Paris Saint Germain | alias | PSG | sì | 1 |

Su 48 partite della prossima giornata: 39 abbinate con il solo `clean_name` (81.2%), 42 con il resolver di produzione (87.5%). I nomi mancanti sono 11: 5 sono gia' nella tabella Understat (li recupera il resolver di produzione senza toccare `clean_name`), i restanti sono varianti non censite (Borussia Monchengladbach, FSV Mainz 05, Atlético Madrid, CA Osasuna, Elche CF, Real Racing Club de Santander). Nota: `clean_name` trasforma `FSV Mainz 05` in `FMainz 05` perche' la lista delle sostituzioni contiene la stringa `SV ` : e' un effetto collaterale della funzione, non un alias mancante.

## 4. Budget (piano gratuito)

Costo misurato: `x-requests-last` = 2 con `regions=eu,uk` e 1 con `regions=eu`, per 1 mercato. Un giro completo delle 5 leghe = 5 chiamate. Aggiornamenti: 2 a settimana (4.348 settimane/mese) piu' un aggiornamento prima di ogni turno infrasettimanale.

| Regioni | Crediti/chiamata | Crediti per giro (5 leghe) | Crediti/mese (2 a settimana) | Crediti/mese (con i turni infrasett.) | Crediti/mese (mese peggiore) | % dei 500 crediti (medio / peggiore) | Sta nel piano gratuito? |
|---|---|---|---|---|---|---|---|
| eu,uk | 2 | 10 | 87.0 | 109.0 | 127.0 | 21.8% / 25.4% | SÌ |
| eu | 1 | 5 | 43.5 | 54.5 | 63.5 | 10.9% / 12.7% | SÌ |

Turni infrasettimanali misurati sui CSV del repository (unione delle 5 leghe, date di mar/mer/gio raggruppate se consecutive o a distanza <= 2 giorni):

| Stagione | Turni infrasettimanali | Media per mese | Massimo in un mese |
|---|---|---|---|
| 2024/25 | 22 | 2.20 | 4 |
| 2025/26 | 17 | 1.89 | 3 |

Il calcolo usa la media peggiore fra le due stagioni e, come mese peggiore, il massimo osservato. Stato della quota rilevato dagli header: 31 crediti gia' usati prima di queste prove, 43 dopo (le prove ne hanno consumati 12), residui 457 su 500.

**Risposta al punto 4.** Sì: con una sola regione servono circa 54 crediti al mese (11% del piano gratuito), con due regioni circa 109 (22%). Il mese peggiore resta abbondantemente sotto i 500 crediti in entrambi i casi.

## 5. Raccomandazione

**Fonte consigliata: The Odds API, piano gratuito (500 crediti/mese), mercato `h2h`, regioni `eu` (1 credito a chiamata).**

Motivi, tutti misurati in questo referto:

1. **Bet365 non serve.** Sulle due stagioni valutate, con lo stesso protocollo della PR #49, la media di mercato de-vigata, il massimo di mercato, Pinnacle e il consenso fra book sono EQUIVALENTI a Bet365 (regola C1-C2-C3): |Δ LogLoss| <= 0,0015, scelte Top Mix coincidenti. Bet365 e' utile come riferimento storico, non come requisito della fonte dal vivo.

2. **Bet365 non e' comunque disponibile**: la chiamata esplicita `bookmakers=bet365` su Serie A restituisce 0 bookmaker e il catalogo ufficiale riporta Bet365 solo come `bet365_au` (AFL/NRL, piani a pagamento). Pinnacle — il book con la LogLoss migliore fra quelli dei CSV (0,9634 contro 0,9719 di Bet365) — e' invece presente in tutte e 5 le leghe.

3. **Il budget sta nel piano gratuito**: con `regions=eu` un giro delle 5 leghe costa 5 crediti, due aggiornamenti a settimana piu' un aggiornamento per ogni turno infrasettimanale fanno circa 54 crediti al mese (11% dei 500), mese peggiore 63. Con `regions=eu,uk` (piu' bookmaker per partita) circa 109 crediti/mese, mese peggiore 127: ancora dentro il piano gratuito.

4. **football-data.co.uk non puo' essere la fonte dal vivo**: il file delle partite in programma esiste e ha le colonne Bet365, ma oggi non contiene NESSUNA partita delle 5 leghe e dichiara un aggiornamento settimanale (venerdi' 17:00 UK / martedi' 13:00 UK). Resta la fonte storica del progetto, che gia' e'.

**Precondizione obbligatoria prima di andare in produzione: l'abbinamento dei nomi.** Con il solo `clean_name` si ferma al 81.2% delle partite della prossima giornata (39/48); con il resolver di produzione (`team_names.resolve_team_name`, che usa tutte le tabelle di alias) si sale al 87.5% (42/48). Restano 6 nomi non censiti da aggiungere a `SoccerMath/team_aliases.py`: `Borussia Monchengladbach`, `FSV Mainz 05`, `Atlético Madrid`, `CA Osasuna`, `Elche CF`, `Real Racing Club de Santander`. La modifica non e' in questo audit (nessun file di `SoccerMath/` e' toccato) e va fatta con la regola del progetto: nessun fuzzy matching, ogni nome dichiarato.

**Rischi aperti (da decidere prima di integrare).** (a) La copertura di Pinnacle non e' garantita su tutte le partite: nei CSV storici manca su 850 partite su 3504: serve una regola di ripiego (consenso de-vigato dei book tornati). (b) Le quote di Pinnacle sono 'dal sito pubblico, con possibile ritardo' (nota del catalogo ufficiale). (c) Il piano gratuito esclude lo storico quote: per il confronto modello/mercato resta solo il flusso live. (d) La copertura dei book puo' cambiare senza preavviso: il controllo va ripetuto a ogni stagione.

## 6. Quadro di sintesi (esito, comando, evidenza)

| # | Voce verificata | Esito | Comando / link | Evidenza |
|---|---|---|---|---|
| 1 | Branch e prerequisiti | OK | git diff --name-only origin/main...HEAD | diff vuoto all'avvio; PR #49 mergiata |
| 2 | Copertura The Odds API sulle 5 leghe | OK | python audit/live_odds_probe.py | 5/5 leghe con HTTP 200, 18-20 eventi e 37-41 bookmaker ciascuna |
| 3 | Bet365 disponibile nella fonte dal vivo | NON OK | bookmakers=bet365 (chiamata esplicita) | HTTP 200, 0 bookmaker restituiti; nel catalogo ufficiale Bet365 esiste solo come bet365_au (AFL/NRL, solo a pagamento) |
| 4 | Pinnacle disponibile nella fonte dal vivo | OK | audit/data/live_odds_probe/probe_summary.json | chiave `pinnacle` presente in tutte e 5 le leghe |
| 5 | Un bookmaker basta al posto di Bet365 (dati storici) | OK | python audit/bookmaker_source_test.py | Avg, Max, Pinnacle, consenso e i singoli book disponibili live: tutti EQUIVALENTE alla regola C1-C2-C3; \|Δ LogLoss\| <= 0,0015 |
| 6 | Aggiornamento orario della quota | OK | confronto last_update dei libri con l'ora della chiamata | aggiornamenti dei libri entro ~6 minuti dalla chiamata; documentazione: 60 s pre-partita |
| 7 | football-data.co.uk: file delle partite in programma | OK | https://www.football-data.co.uk/fixtures.csv | il file esiste (HTTP 200, 94 colonne, B365 pre e chiusura) |
| 8 | football-data.co.uk: copertura delle 5 leghe oggi | NON OK | python audit/live_odds_probe.py | 0 righe su 46: solo E2, E3, EC, SC1, SC2, SC3, SP2, date 02-05/10/2026 (gia' giocate) |
| 9 | Terza fonte gratuita | NON VERIFICABILE | documentazione OddsPapi | nessuna chiave nel repository e rete bloccata: solo documentazione |
| 10 | Abbinamento nomi della prossima giornata | NON OK | python audit/live_odds_match.py | 39/48 con clean_name (81.2%); 42/48 (87.5%) con il resolver di produzione |
| 11 | Budget nel piano gratuito | OK | python audit/live_odds_feasibility.py | mese peggiore 127 crediti su 500 |
| 12 | Diff finale limitato a audit/ | OK | git diff --name-only origin/main...HEAD | 19 file, cartelle: audit |
| 13 | CI: Suite e Audit verdi, Replay saltato | OK | gh pr checks <numero PR> | Suite: success (run 37862012240) · Audit: success (run 37862012206) · Replay: skipped (run 37862012208) |

## 7. Limiti dichiarati

- Le chiamate reali sono UNO snapshot del 2026-10-08 (3 run). Copertura, bookmaker e crediti possono cambiare: ogni numero 'live' va riletto come 'misurato in quella data'.
- Il secret ODDS_API_KEY e' stato usato senza mai leggerne il valore (il token dell'agente non ha il permesso: HTTP 403). L'esito della verifica e' ricavato da `${{ secrets.ODDS_API_KEY != '' }}` e dal codice di risposta HTTP.
- Le prove di rete sono state eseguite da un workflow GitHub TEMPORANEO, rimosso prima della chiusura: nel diff finale non resta traccia del workflow, mentre gli esiti committati restano in audit/data/live_odds_probe/.
- Il confronto fra book (punto 1) usa le colonne pre-chiusura dei CSV: la fonte non dichiara l'orario di rilevazione, quindi 'pre-chiusura' e' la dicitura della commessa.
- I turni infrasettimanali del budget sono ricostruiti dalle date dei CSV (mar/mer/gio raggruppate se consecutive o entro 2 giorni): una ricostruzione, non il calendario ufficiale.
- L'abbinamento nomi e' misurato sulla sola prossima giornata disponibile (48 partite): le squadre promosse di altre leghe non ancora incontrate possono aggiungere altri nomi mancanti.
- Terza fonte (OddsPapi): solo documentazione, nessuna prova. Non e' un'alternativa verificata.

## 8. Verdetto di mergeability

**MERGEABLE**

| Criterio | Esito | Evidenza |
|---|---|---|
| Il diff tocca solo audit/ | OK | git diff --name-only origin/main...HEAD: audit |
| Nessun file di SoccerMath/ modificato | OK | il confronto fra book e l'abbinamento nomi sono sola lettura |
| Nessun workflow temporaneo nel diff | OK | il workflow di prova e' stato rimosso prima della chiusura |
| Suite test verde | OK | gh pr checks: Suite success (run 37862012240) |
| Audit Top Mix verde | OK | gh pr checks: Audit success (run 37862012206) |
| Replay saltato (o verde) | OK | gh pr checks: Replay skipped (passi 3-19 del job skipped) (run 37862012208) |
