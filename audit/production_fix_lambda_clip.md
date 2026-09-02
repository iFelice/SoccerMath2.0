# Production fix — clip dei lambda in `get_full_poisson()`

> **Cosa fa questo file.** Contiene il codice pronto per l'incolla manuale in
> `SoccerMath/app.py`. **Nessun file in `SoccerMath/` è stato modificato**: la
> patch va applicata a mano da chi legge. Tutto il contenuto sta solo in questo
> markdown dentro `audit/`.

## Perché

Negli audit precedenti (`audit/diagnose_mle_attack_defence.py` e soprattutto
`audit/diagnose_mle_vs_baseline_clipped.py`) si è visto che in rari casi
l'euristica attuale produce lambda estremi (fuori dal range `[exp(-6), exp(3)]`).
Sono **6 partite su 3504** (0.17%) nel campione VALIDATION 2024/25 + TEST 2025/26,
ma pesano moltissimo sul Log Loss: es. Bundesliga 1X2 LogLoss `1.0431 → 1.0103`,
Ligue 1 `1.0342 → 1.0028`, La Liga `1.0127 → 0.9870` solo aggiungendo il clip.
Applicare lo stesso clip usato nella variante MLE recupera quasi tutto il divario
verso la MLE a **costo computazionale nullo**, senza toccare la logica di stima
(`team_attr`, `avg_h`/`avg_a` restano identici).

Bound validati (identici a `mle_lambdas()` in `diagnose_mle_attack_defence.py`,
log-spazio `[-6, 3]`):

```
exp(-6) = 0.002479
exp(3)  = 20.0855
```

## 1. Dove va applicata la modifica

- File: **`SoccerMath/app.py`**
- Funzione: **`get_full_poisson()`**, che inizia a **riga 552 circa**.
- Oggi la funzione passa `h_e`/`a_e` direttamente a `poisson.pmf()` (righe 553–554)
  **senza alcun limite**.
- Il clip va messo **DENTRO la funzione**, in testa, **non** nei punti di chiamata.
  In questo modo si applica automaticamente a tutti i chiamanti. I 5 punti che
  chiamano `get_full_poisson()` oggi sono (solo per riferimento, **NON** vanno
  toccati):

  | Riga | Contesto |
  |---|---|
  | 522  | backtest storico (`m_p = get_full_poisson(...)`) |
  | 685  | calcolo segnali/mercati (`m_poisson = get_full_poisson(...)`) |
  | 739  | (`m = get_full_poisson(...)`) |
  | 774  | versione aggiustata (`m_adj = get_full_poisson(h_exp, a_exp)`) |
  | 1053 | flusso live/API (`m = get_full_poisson(...)`) |

  Mettendo il clip dentro la funzione, tutti e 5 sono coperti con una sola modifica.

## 2. Codice ATTUALE (così com'è ora in `app.py`, righe 552–564)

```python
def get_full_poisson(h_e, a_e, max_goals=15):
    h_p = [poisson.pmf(i, h_e) for i in range(max_goals)]
    a_p = [poisson.pmf(i, a_e) for i in range(max_goals)]
    matrix = np.outer(h_p, a_p)
    def get_u(limit):
        return sum(matrix[i,j] for i in range(max_goals) for j in range(max_goals) if i+j < limit)
    return {
        "1": np.sum(np.tril(matrix, -1)),
        "X": np.sum(np.diag(matrix)),
        "2": np.sum(np.triu(matrix, 1)),
        "u25": get_u(2.5),
        "gg": (1-h_p[0])*(1-a_p[0])
    }
```

## 3. Codice MODIFICATO (incollare al posto del blocco qui sopra)

Identico in tutto — firma, logica interna, ordine delle chiavi nel dict di
ritorno — tranne le **due righe di clip aggiunte in testa** su `h_e` e `a_e`.

```python
def get_full_poisson(h_e, a_e, max_goals=15):
    # Clip dei lambda in ingresso al range validato in audit/ (log-spazio [-6, 3]).
    # Evita lambda estremi mal calibrati (~0.17% delle partite) senza cambiare la
    # logica di stima. Vedi audit/diagnose_mle_vs_baseline_clipped.py.
    h_e = min(max(h_e, 0.002479), 20.0855)  # [exp(-6), exp(3)]
    a_e = min(max(a_e, 0.002479), 20.0855)  # [exp(-6), exp(3)]
    h_p = [poisson.pmf(i, h_e) for i in range(max_goals)]
    a_p = [poisson.pmf(i, a_e) for i in range(max_goals)]
    matrix = np.outer(h_p, a_p)
    def get_u(limit):
        return sum(matrix[i,j] for i in range(max_goals) for j in range(max_goals) if i+j < limit)
    return {
        "1": np.sum(np.tril(matrix, -1)),
        "X": np.sum(np.diag(matrix)),
        "2": np.sum(np.triu(matrix, 1)),
        "u25": get_u(2.5),
        "gg": (1-h_p[0])*(1-a_p[0])
    }
```

### Diff (solo per chiarezza — è il minimo indispensabile)

```diff
 def get_full_poisson(h_e, a_e, max_goals=15):
+    # Clip dei lambda in ingresso al range validato in audit/ (log-spazio [-6, 3]).
+    # Evita lambda estremi mal calibrati (~0.17% delle partite) senza cambiare la
+    # logica di stima. Vedi audit/diagnose_mle_vs_baseline_clipped.py.
+    h_e = min(max(h_e, 0.002479), 20.0855)  # [exp(-6), exp(3)]
+    a_e = min(max(a_e, 0.002479), 20.0855)  # [exp(-6), exp(3)]
     h_p = [poisson.pmf(i, h_e) for i in range(max_goals)]
     a_p = [poisson.pmf(i, a_e) for i in range(max_goals)]
     matrix = np.outer(h_p, a_p)
```

> Nota sul nome dei parametri: la richiesta parla di "clip su `h_e` e `h_a`", ma
> nella firma reale i due argomenti si chiamano **`h_e`** (lambda casa) e
> **`a_e`** (lambda trasferta). Il clip è quindi applicato a `h_e` e `a_e`.

## 4. Altri punti che calcolano Poisson bypassando `get_full_poisson()`

Ho cercato in tutto `SoccerMath/app.py` altre chiamate dirette a `poisson.pmf()`
(o calcoli Poisson manuali con `math.exp`/`factorial`/pmf a mano) che **non**
passano da `get_full_poisson()`.

**Risultato: NON esistono altri punti da correggere.**

- `poisson` è importato una sola volta (`from scipy.stats import poisson`, riga 13).
- Le uniche chiamate a `poisson.pmf()` in tutto il file sono le **righe 553 e 554**,
  entrambe **dentro** `get_full_poisson()`. Applicando il clip lì, sono coperte.
- **Non esiste** alcuna funzione `calcola_ou_gg()` in `SoccerMath/app.py` (né altre
  `calcola_*` che calcolino probabilità Poisson): le uniche definizioni `calcola_*`
  sono `calcola_stagione_calcolo()` (riga 57, gestione date) e `calcola_segnali()`
  (riga 566, moltiplicatori attacco/difesa) — nessuna delle due tocca la Poisson.
- Non ci sono calcoli Poisson "fatti a mano" (nessun `factorial`, nessuna pmf
  espansa con `exp(-lam)*lam**k/k!`). L'unico `math.exp(...)` del file è a **riga
  529**, dentro il backtest, ma è la **probabilità di pareggio del modello Elo**
  (`p_draw = 0.27 * math.exp(-((dr / 320.0) ** 2))`), **non** un calcolo Poisson:
  non va toccato.

Quindi, per questa base di codice, **basta la singola modifica dentro
`get_full_poisson()`**: nessun altro intervento è necessario. Se in futuro venisse
aggiunta una nuova funzione che chiama `poisson.pmf()` con lambda calcolati
direttamente (senza passare da `get_full_poisson()`), andrà applicato lo stesso
clip `min(max(lam, 0.002479), 20.0855)` anche lì.

## 5. Verifica rapida dopo l'incolla

- Il comportamento resta **identico** per la stragrande maggioranza delle partite:
  il clip interviene solo quando un lambda esce da `[0.002479, 20.0855]` (nel
  campione di audit: 6 partite su 3504, ~0.17%).
- Nessuna dipendenza nuova: `min`/`max` sono built-in; i costanti sono i valori di
  `exp(-6)`/`exp(3)` già usati e validati in `audit/`.
- Nessuna variazione di firma, di chiavi del dict di ritorno, né dell'ordine delle
  chiavi: i 5 chiamanti (522, 685, 739, 774, 1053) continuano a funzionare senza
  modifiche.
