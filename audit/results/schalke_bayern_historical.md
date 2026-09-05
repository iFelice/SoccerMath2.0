# Schalke–Bayern 92,1%: GET JSONBin + ricostruzione su commit storico

**Branch:** `arena/01a0727e-soccermath2-0`  
**Vincoli:** nessuna PUT JSONBin, nessun merge, nessuna modifica a formule/soglie/pesi/dedup.

Strumenti: `audit/fetch_jsonbin_match.py` (GET `/latest` only), `audit/reconstruct_topmix_match.py --git-ref` (git archive di `SoccerMath/database`, HEAD invariato).

---

## 1. GET JSONBin (sola lettura)

**In questo sandbox: non eseguita.**  
`JSONBIN_API_KEY` e `JSONBIN_BIN_ID` assenti (env, `SoccerMath/.env`, `st.secrets`). `gh secret list` non è autorizzato (403). Nessuna GET di rete, nessuna PUT.

Output locale: `audit/results/jsonbin_schalke_bayern.json` (`ok: false`, `put_called: false`).

Il workflow `.github/workflows/topmix_audit.yml` tenta la stessa GET se i secrets esistono su GitHub; l’artifact conterrà **tutti i campi** della riga (incluso `salvato_il` esatto). Senza secrets il job resta verde e registra la mancanza.

Senza `salvato_il` **non** si può identificare l’HEAD di `origin/main` al click. `git log origin/main --until=<salvato_il>` è implementato (`main_head_at`) e resta inutilizzato.

---

## 2. Ricostruzione sui commit dati (CSV/xG/Elo storici)

Le funzioni di produzione sono quelle del working tree. I file di dati sono estratti con `git archive` dal commit indicato (nessun `git checkout`). Cache `get_league_engine` / Elo svuotate a ogni cambio ref.

| Commit dati | Quando (UTC) | Cosa cambia | Selettore A | `prob_val` | Gap vs 92,1 | xG Schalke | xG Bayern |
|---|---|---|---|---|---|---|---|
| `0695e9e` | 2026-09-05 16:14 | archivio xG + medie derivate | Vittoria Bayern | **75,9%** | −16,2 | chiave, 1 match, shrinkage | chiave, 1 match, shrinkage |
| `bcb6b60` | 2026-09-05 14:04 | live CSV | Vittoria Bayern | **89,7%** | −2,4 | **miss** → fallback gol | xG **senza** campo `matches` (ratio raw) |
| `73586bd` | 2026-09-05 01:35 | live CSV | Vittoria Bayern | 89,7% | −2,4 | miss | raw, no `matches` |
| `afc58d2` | 2026-09-04 19:57 | live CSV | Vittoria Bayern | 89,7% | −2,4 | miss | raw, no `matches` |
| `4d775ca` | 2026-09-04 01:34 | live CSV | Vittoria Bayern | 89,7% | −2,4 | miss | raw, no `matches` |

**Il 92,1% non è riprodotto su nessuno di questi snapshot.** Non è stato forzato.

### 2.1 Dettaglio 0695e9e (post-archivio xG) — già visto ieri

- Poisson «Vittoria Bayern» 76,79%; Elo 74,65%
- `0.6 * 0.7679 + 0.4 * 0.7465 = 0.759` → **75,9%**
- Fonte forza: xG con `PRIOR_MATCHES=6` (1 partita a testa)

### 2.2 Dettaglio `bcb6b60` (pre-archivio xG, più vicino al 92,1)

Verificato con `reconstruct_match(..., git_ref="bcb6b60")`:

- Schalke: `xg_key_hit=False` → **goals_fallback**, `att0_pure=0.684`, `def0_pure=1.275`
- Bayern: xG `{xG_avg: 2.652, xGA_avg: 0.749}` **senza `matches`** → `xg_raw_no_matches_field` (niente shrinkage), `att0_pure=1.981`, `def0_pure=0.506`
- Medie lega xG file: `league_xg=1.339`, `league_xga=1.480` (25 squadre)
- Poisson 1/X/2: 0,45% / 1,87% / **97,67%**
- Elo 1/X/2: 12,34% / 9,95% / **77,71%** (1401,8 vs 1791,5, HA 70)
- Mix: `0.6 * 0.9767 + 0.4 * 0.7771 = 0.8968` → **89,7%**
- Selettore B: stesso mercato, 89,7%

L’ipotesi «1 xG match + PRIOR=6 sposta tutto» è **confermata in direzione**: con xG shrunk si scende a 75,9%; senza chiave xG Schalke e senza shrinkage Bayern si sale a 89,7%. **Non basta a 92,1.**

Candidati nome API su 0695e9e: `Schalke`/`Bayern` e alias mappati → 75,9%; `FC Schalke 04`/`FC Bayern München` → GG 67,9% (Bayern non mappato). Nessun 92,1.

---

## 3. Sospetti residui (nessuna spiegazione finale)

Il 92,1% resta irreproducibile sul motore di produzione + dati committati. Sospetti **non discriminati** (mancano ancora gli stessi pezzi di ieri):

1. **Riga JSONBin** (`prob_sicuro`, `mercato_standard`, `pronostico_sicuro`, `tipo`, `salvato_il`, `model_version`, `match_id`) — GET non fatta qui.
2. **Campo mostrato in UI** diverso da `prob_val` (es. Poisson 97,7% su `bcb6b60`, o un altro mercato).
3. **Cache Streamlit** `get_league_engine` ttl 3600 / `fetch_and_calc_top_mix` ttl 1800: un click dopo `0695e9e` poteva ancora servire l’engine pre-xG (89,7%), o un mix cache/file non committato.
4. **Nomi API al click** ≠ `Schalke`/`Bayern` (lo snapshot TIMED/SCHEDULED manca; i nomi football-data *attuali* non sono lo snapshot).
5. **Elo al millisecondo** diverso dal ricalcolo sui CSV del commit (Elo non è persistito).
6. Per arrivare a 92,1 sul mix di `bcb6b60` servirebbe Elo «2» ≈ 83,8% invece di 77,7% — possibile solo con un dump Elo diverso, non verificato.

Non si è cercato un insieme di soglie/pesi che «faccia uscire» 92,1.

JSON macchina: `audit/results/schalke_bayern_historical.json`.

---

## 4. Classificazione pre/post shrinkage — nessuna correzione a mano

Senza la riga JSONBin non si sa se Schalke–Bayern è pre-fix mal taggato.

`classify_entry` / `entry_era_by_time`: **nessun bug riproducibile del parser di data**. Test aggiunto:

- `salvato_il=04/09/2026 15:25` (era **pre** rispetto al merge `dc192d5`) + `model_version=post_shrinkage_v1` → status `already_post_shrinkage_v1`.

È la regola attuale: la versione esplicita vince sul tempo. `save_prediction_entry` scrive sempre `post_shrinkage_v1` da quando il versionamento è in produzione (`31b7645`, 2026-09-04 17:31 UTC, dopo il merge del fix).

**Fix proposto, non applicato:** nessuno. Invertire la precedenza (il tempo batte `model_version`) romperebbe i test esistenti e non è giustificato senza la riga reale. Vietato `--apply` / PUT / correzione a mano della riga.

---

## 5. P2 `standardizza_mercato` (intervento codice, non audit)

Riproduzione: `standardizza_mercato("Vittoria Stade Rennais - Top Mix", "Angers SCO", "Stade Rennais")` era `ALTRO` perché il confronto usava solo `clean_name` (`Rennes` ⊄ testo). Idem `Barça` → `Barcelona`.

Fix minimo: si confrontano **nome grezzo e** `clean_name`.  
Strutturale: `codice_mercato_selezionato` al momento della generazione (Top Mix / Analisi Rapida / Billy fallback-errore); `save_prediction_entry(..., mercato_standard=)` usa quel codice; `standardizza_mercato` resta fallback. **Nessuna migrazione** dei record esistenti. Dedup per `match_id` invariata.

Test: tutti gli alias di `TEAM_NAME_MAP` (non una selezione a mano) + mock di `save_prediction_entry`.
