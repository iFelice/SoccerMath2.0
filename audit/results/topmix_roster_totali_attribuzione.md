# Fedeltà del replay: effetto separato dei Totali e del fix roster (PR #47, round 2)

Domanda: quanto della perdita di fedeltà tra replay e registro dipende dalla rimozione dei
Totali dal Top Mix visibile, e quanto dal fix del roster nel replay?

**Dati.** Esportazione OFFLINE del registro: `audit/results/replay_sym_offline/registro_offline_fuso.json`
(131 righe Top Mix, tutte `topmix_gate025_ens06_v1`, di cui 68 Totali). Non è il registro vivo:
le cifre valgono per questa esportazione, non per il registro di produzione.

**Replay.** Quattro esecuzioni con `--fixtures csv --ref c06818e` (stessi istanti, stesse fixture):

- `main` senza fix: `SoccerMath/replay_legacy_topmix.py` di `main` (c06818e).
- `main` con fix: stesso codice di `main`, con `db_snapshot.py` e `replay_legacy_topmix.py` del branch
  copiati nel clone (isola l'effetto del roster senza cambiare la logica di selezione).
- `branch` senza fix e `branch` con fix: il branch 633e477 con `roster_fallback` spento e acceso.

**Chiave di confronto.** (partita, data, `mercato_standard`); coincide se la probabilità è uguale
a un decimale. Script: `attribuzione.py` (esecuzione locale, output in `/home/user/evidence/fedelta/`).

| replay | righe nel replay | coincidono (su 131) | non coincidono: Totali | non coincidono: 1X2 |
|---|---:|---:|---:|---:|
| main, senza fix roster | 158 | 95 | 0 | 36 |
| main, con fix roster | 149 | 100 | 0 | 31 |
| branch, senza fix roster | 93 | 27 | 68 | 36 |
| branch, con fix roster | 91 | 32 | 68 | 31 |

**Lettura.**

- **Totali (−68).** Il branch non produce più i Totali (per progetto): le 68 righe Totali del registro
  non hanno più controparte. Da 95 a 27 coincidenze senza fix, da 100 a 32 con il fix.
- **Roster (+5, nessuna perdita).** Il fix recupera 5 righe 1X2 in entrambi i lati, riga per riga,
  e non ne perde nessuna. Le 5 righe: Betis–Real Madrid 04/09 (2), Leverkusen–Union Berlin 05/09 (1),
  Real Madrid–Vallecano 12/09 (1), Atletico Madrid–Osasuna 16/09 (1), Bayern–Union Berlin 18/09 (1).
- **Ordine di grandezza confermato dalla CI.** Nella CI della PR #46 (main, con Totali) la fedeltà
  del replay era **97/205**; nella CI di questo branch è **23/205** (run `37843698455`, annotazione
  "Fedeltà"). Il calo (−74) è dello stesso ordine delle 68 righe Totali qui sopra. La CI usa il
  registro vivo e un perimetro diverso: il confronto è di direzione, non di cifra.

**Non verificato.** Il registro vivo (206 righe) non è leggibile dalla sandbox: l'attribuzione
esatta sul registro di produzione resta NON VERIFICABILE in locale. Le cifre della CI sono quelle
dell'annotazione, non di un artefatto scaricato.

**Verifica ipotesi "il verificatore passava per i Totali" (PR #39–#46).** Annotazioni CI della PR #46
(`check-runs/.../annotations`): nel campione di 6 righe le uniche coincidenze sono
**Brighton–Arsenal GG 63,2** (Attuale, salvata 15/09) e **Auxerre–Brest OVER_2.5 64,0** (Attuale, salvata 15/09),
entrambe Totali. Milan–Lecce 1 64,5 (salvata 15/09) risulta "differisce" (77,7). L'ipotesi è
**confermata sulle annotazioni**: il verificatore passava grazie a due Totali, che dipendono dal solo
Poisson e quindi non dal roster.
