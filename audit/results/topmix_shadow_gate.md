# Gate shadow: il veto |P-E| < 0.25 come penalita' continua

**Definizione (referto `margini_migliorabili_topmix.md` §11quater):** `conf_shadow = conf * 0.25 / (0.25 + d)`, ammissione ombra = `conf_shadow >= min_conf`. Formula implementata in `prediction_registry.gate_shadow_confidence`.

Fonte: `topmix_selector_replay_rows.csv` (3422 candidate). Sola lettura: nessuna riga del registro toccata.

**Consistenza con l'artefatto committato: OK**

| grandezza | valore |
|---|---|
| righe ammesse dal selettore reale | 1865 |
| ...che l'ombra ammetterebbe ancora (**robuste**) | 1029 (55%) |
| ...che l'ombra NON ammetterebbe (**fragili**) | 836 (45%) |
| righe bloccate dal gate (d >= 0.25) | 194 |
| ...riammesse dall'ombra | 0 |

### Ammesse: robuste vs fragili

| gruppo | n | prob media | conf_shadow media | d medio | hit | Brier |
|---|---:|---:|---:|---:|---:|---:|
| tutte le ammesse | 1865 | 66.4% | 54.3% | 0.071 | 62.0% | 0.2312 |
| robuste | 1029 | 66.7% | 63.5% | 0.013 | 62.5% | 0.2298 |
| fragili | 836 | 66.0% | 42.8% | 0.143 | 61.4% | 0.2329 |

### Bloccate dal gate: la scala conf_shadow (nessuna riammissione)

| n | prob media | d medio | conf_shadow media | max conf_shadow | riammesse dall'ombra |
|---|---:|---:|---:|---:|---:|
| 194 | 65.8% | 0.304 | 29.9% | 41.2% | 0 |

Nota: Nessuna riga bloccata dal gate puo' essere riammessa dalla variante ombra: d >= 0.25 implica fattore <= 1/2, quindi conf_shadow <= conf/2 <= 0.5 < 0.55 (soglia 1X2).

Lettura: su validation storica gia' esaminata robuste e fragili hanno hit/Brier vicini (le tabelle NON tarano nulla e non provano nessun margine: il confronto va fatto in cieco sul 2026/27). Il valore operativo e' la misura APPAIATA che i campi `gate_shadow_confidence`/`gate_shadow_ammessa` del registro renderanno possibile sulle righe giocate: Brier della conf_shadow vs Brier della conf reale, per gruppo. Le 194 bloccate restano misurabili solo ex-post/harness: la produzione non le mostra ne' le gioca (referto §11quater).
