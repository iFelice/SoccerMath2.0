# Filtro di concordanza sulle scelte di mercato (`topmix_mercato_v3`)

## Regola dichiarata (prima dei numeri; questa sezione non viene modificata dopo)

**Campione.** Le 1.302 scelte di mercato del replay `topmix_mercato_v3` (PR #49),
ciascuna con probabilità di mercato `p_m` dell'esito scelto e probabilità del
modello Drago `p_d` per lo stesso esito, walk-forward come in produzione
(blend 0,25 Poisson + 0,75 Elo, colonne `m0/m1/m2` del frame della PR #49).
Scarto = `p_d − p_m`. Il replay deve stare in parità con la PR #49
(1302 / 1144 / 335, Δn = 0) prima di ogni numero di questo referto.

**Filtro proposto.** Una scelta passa se `p_m ≥ 0,75` **oppure** `|scarto| ≤ 0,05`.
Soglie fisse: nessuna ricerca di soglie alternative, in nessuna direzione.

**Gruppi.**
- "passa" ed "esclusa" sono calcolati sulle sole scelte con `p_m < 0,75`
  (così il confronto è a parità di probabilità di mercato e il criterio
  sotto test è quello di concordanza): "passa" = `|scarto| ≤ 0,05`,
  "esclusa" = `|scarto| > 0,05`.
- Le escluse si dividono in "modello più alto" (scarto > +0,05) e
  "modello più basso" (scarto < −0,05).
- Il filtro intero in produzione manterrebbe anche le scelte con `p_m ≥ 0,75`
  (passano per definizione): l'esito della regola è riportato anche con
  "passa" esteso a tutte le scelte mantenute dal filtro, come sola sensibilità.
  Il verdetto segue la definizione principale (solo `p_m < 0,75`).

**Incertezza.** Bootstrap a blocchi lega × stagione × data, 2.000 repliche con
reimmissione, IC 95% percentile, seme fisso. `f − p_m` = frequenza di vincita
del gruppo meno la `p_m` media dello stesso gruppo (con segno). La differenza
fra due gruppi è appaiata: gli stessi draw di blocchi valutano entrambi.

**Filtro di concordanza — regola di decisione.** Il filtro si propone per la
produzione solo se valgono entrambe:

- **(a)** nel gruppo "esclusa" l'IC 95% di `f − p_m` è tutto sotto zero;
- **(b)** l'IC 95% della differenza (`f − p_m` del gruppo "passa") −
  (`f − p_m` del gruppo "esclusa") è tutto sopra zero.

In ogni altro caso il filtro non si adotta e lo scarto resta un'informazione
di contesto.

Le tabelle su fasce di `p_m`, regressione logistica e incrocio con la colonna
"d'accordo" sono di contesto: non entrano nella regola. Le soglie 0,75 / 0,05
e i bordi delle fasce non vengono toccati dopo aver visto i dati.

Generato da `audit/filtro_concordanza_scarto.py` il 2026-10-10T21:59:25Z (commit `f7b224d`, branch `arena/0dbf3f5a-soccermath2-0`). Bootstrap: 2000 repliche a blocchi lega × stagione × data, seme 20261010. Nessuna rete, nessuna modifica a `SoccerMath/`.

Replay di provenienza in parità con la PR #49: **SÌ** (1302 scelte di mercato su 3504 righe di campione; max scarto de-vig vs colonne `pre*` PR #49: 1.11e-16).

## 1. Gruppi passa / esclusa (solo scelte con p_m < 0,75)

| gruppo | n | p_m media | frequenza di vincita f | f − p_m | IC 95% a blocchi |
|---|---:|---:|---:|---:|---|
| passa (|scarto| ≤ 0,05) | 561 | 63,31 % | 64,88 % | 1,58 pt | [-2,36 pt; 5,39 pt] |
| esclusa (|scarto| > 0,05) | 555 | 63,28 % | 64,50 % | 1,22 pt | [-2,51 pt; 5,02 pt] |
| esclusa — modello più alto (scarto > +0,05) | 385 | 63,81 % | 63,64 % | -0,18 pt | [-4,66 pt; 4,47 pt] |
| esclusa — modello più basso (scarto < −0,05) | 170 | 62,08 % | 66,47 % | 4,39 pt | [-2,71 pt; 11,39 pt] |

Informazione (fuori regola): le scelte con `p_m ≥ 0,75` passano per definizione: n = 186, p_m media 79,64 %, f = 84,41 %, f − p_m = 4,77 pt [-0,41 pt; 9,56 pt].

## 2. Stessa tabella dentro le fasce di p_m

| fascia | gruppo | n | p_m media | f | f − p_m | IC 95% a blocchi |
|---|---|---:|---:|---:|---:|---|
| [0,55-0,60) | passa (|scarto| ≤ 0,05) | 199 | 57,30 % | 56,28 % | -1,02 pt | [-7,84 pt; 5,79 pt] |
| [0,55-0,60) | esclusa (|scarto| > 0,05) | 189 | 57,26 % | 58,73 % | 1,47 pt | [-5,04 pt; 8,07 pt] |
| [0,55-0,60) | esclusa — modello più alto (scarto > +0,05) | 112 | 57,31 % | 57,14 % | -0,17 pt | [-8,78 pt; 8,88 pt] |
| [0,55-0,60) | esclusa — modello più basso (scarto < −0,05) | 77 | 57,18 % | 61,04 % | 3,86 pt | [-6,88 pt; 14,24 pt] |
| [0,60-0,65) | passa (|scarto| ≤ 0,05) | 143 | 62,20 % | 60,14 % | -2,06 pt | [-10,21 pt; 6,32 pt] |
| [0,60-0,65) | esclusa (|scarto| > 0,05) | 149 | 62,08 % | 59,06 % | -3,02 pt | [-10,94 pt; 4,75 pt] |
| [0,60-0,65) | esclusa — modello più alto (scarto > +0,05) | 111 | 62,13 % | 56,76 % | -5,37 pt | [-14,79 pt; 3,93 pt] |
| [0,60-0,65) | esclusa — modello più basso (scarto < −0,05) | 38 | 61,93 % | 65,79 % | 3,86 pt | [-11,65 pt; 19,17 pt] |
| [0,65-0,75) | passa (|scarto| ≤ 0,05) | 219 | 69,49 % | 75,80 % | 6,31 pt | [0,57 pt; 11,94 pt] |
| [0,65-0,75) | esclusa (|scarto| > 0,05) | 217 | 69,36 % | 73,27 % | 3,91 pt | [-1,91 pt; 9,32 pt] |
| [0,65-0,75) | esclusa — modello più alto (scarto > +0,05) | 162 | 69,46 % | 72,84 % | 3,38 pt | [-3,34 pt; 10,16 pt] |
| [0,65-0,75) | esclusa — modello più basso (scarto < −0,05) | 55 | 69,05 % | 74,55 % | 5,50 pt | [-7,11 pt; 16,47 pt] |

## 3. Regressione logistica dell'esito (1 = vinta)

Modello A: `logit P(vinta) = b0 + b1 · logit(p_m) + b2 · scarto`. Modello B: scarto diviso in parte positiva `max(scarto, 0)` e parte negativa `min(scarto, 0)`. IC 95% dallo stesso bootstrap a blocchi.

| modello | coefficiente | stima | IC 95% a blocchi | repliche valide |
|---|---|---:|---|---:|
| A: y ~ logit(p_m) + scarto | b0 (costante) | -0,1259 | [-0,3696; 0,1088] | 2000 |
| A: y ~ logit(p_m) + scarto | b1 logit(p_m) | 1,4068 | [1,0556; 1,8127] | 2000 |
| A: y ~ logit(p_m) + scarto | b2 scarto | -1,4816 | [-3,3829; 0,1991] | 2000 |
| B: y ~ logit(p_m) + scarto⁺ + scarto⁻ | b0 (costante) | -0,2085 | [-0,5137; 0,0854] | 2000 |
| B: y ~ logit(p_m) + scarto⁺ + scarto⁻ | b1 logit(p_m) | 1,4231 | [1,0673; 1,8326] | 2000 |
| B: y ~ logit(p_m) + scarto⁺ + scarto⁻ | b2 scarto positivo max(s,0) | -0,3908 | [-3,4404; 2,6608] | 2000 |
| B: y ~ logit(p_m) + scarto⁺ + scarto⁻ | b3 scarto negativo min(s,0) | -3,2049 | [-7,4738; 0,5525] | 2000 |

## 4. Incrocio con la colonna "d'accordo" di produzione

Colonna `accordo` del selettore di produzione: modello e mercato sullo stesso esito ed entrambi ≥ 0,55 (`market_odds.SOGLIA_ACCORDO`).

| gruppo | n | p_m media | f | f − p_m | IC 95% a blocchi |
|---|---:|---:|---:|---:|---|
| escluse già "senza accordo" (accordo = False) | 111 | 59,02 % | 63,06 % | 4,04 pt | [-4,69 pt; 12,54 pt] |
| escluse "d'accordo" (accordo = True) | 444 | 64,35 % | 64,86 % | 0,52 pt | [-3,57 pt; 4,88 pt] |
| tutte le escluse | 555 | 63,28 % | 64,50 % | 1,22 pt | [-2,51 pt; 5,02 pt] |

Delle 555 escluse, **111** hanno già la colonna "d'accordo" a False (il filtro non aggiungerebbe nulla su queste) e **444** sono "d'accordo": il loro f − p_m è quello della seconda riga.

## 5. Hit rate prima e dopo il filtro (solo descrittivo)

| insieme | n | vinte | hit rate |
|---|---:|---:|---:|
| insieme completo (scelte di mercato) | 1302 | 879 | 67,51 % |
| dopo il filtro (solo scelte che passano) | 747 | 521 | 69,75 % |
| scelte perse (escluse) | 555 | 358 | 64,50 % |

Scelte perse dal filtro: **555** (hit rate 64,50 %).

## 6. Esito della regola (a)(b)

| condizione | misura | IC 95% a blocchi | esito |
|---|---|---|---|
| (a) IC 95% di f − p_m del gruppo "esclusa" tutto sotto zero | f − p_m = 1,22 pt | [-2,51 pt; 5,02 pt] | NON SUPERATA |
| (b) IC 95% di (f − p_m)passa − (f − p_m)esclusa tutto sopra zero | differenza = 0,36 pt | [-5,20 pt; 6,11 pt] | NON SUPERATA |

**Verdetto: IL FILTRO NON SI ADOTTA** — non valgono (a) e (b): lo scarto resta un'informazione di contesto, come da regola dichiarata.

Sensibilità (gruppo "passa" esteso a tutte le scelte mantenute dal filtro, incluse `p_m ≥ 0,75`): differenza (f − p_m) = 1,15 pt [-3,93 pt; 6,04 pt]; condizione (b) non superata anche in questa lettura. Il verdetto resta quello della definizione principale.

## 7. Limiti dichiarati

- Le stagioni 2024/25 e 2025/26 sono già state usate dal progetto: l'ipotesi del filtro è nuova, ma i dati non sono vergini. L'ipotesi è stata formulata dopo aver visto più volte queste stagioni.
- Le probabilità di mercato vengono dai CSV storici B365 pre-chiusura de-vigati proporzionalmente (fonte del replay della PR #49), non dalle quote live di produzione.
- Lo scarto p_d − p_m è calcolato sullo stesso esito scelto dal mercato: non è uno scarto medio sulle tre vie.
- I bootstrap a blocchi lega × stagione × data tengono conto della correlazione entro la stessa giornata di lega; non delle altre dipendenze (formazioni, mercati comuni).
- La regressione logistica è associativa: il coefficiente dello scarto non identifica un effetto causale del modello.
- Colonna "d'accordo": definizione di produzione (stesso esito, entrambi ≥ 0,55). Nessuna soglia alternativa è stata cercata.
- Nessuna modifica a SoccerMath/ né a app.py; nessun --write; nessuna chiamata a The Odds API.
