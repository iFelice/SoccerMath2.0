# Top Mix: PRIMA (main) contro DOPO (branch) sul replay storico point-in-time

- main: `replay_legacy_topmix.json` - ref `c06818e` - click 103 - leak_ok True
- branch: `replay_legacy_topmix.json` - ref `c06818e` - click 103 - leak_ok True
- Stesse fixture (CSV), stessi istanti, stesso database point-in-time: cambia solo il selettore.

## Variante `current`

### (i) Totali del vecchio Top Mix

| mercato | nel main | sparite (nessun 1X2) | rivalutate su 1X2 |
|---|---:|---:|---:|
| OVER_2.5 | 7 | 5 | 2 |
| UNDER_2.5 | 13 | 11 | 2 |
| GG | 20 | 19 | 1 |
| NG | 0 | 0 | 0 |

### (ii) Partite che entrano con un 1X2

- nuove (il main non aveva nulla): **7**; hit rate: 85.7% (6/7 giudicate)
- rivalutate (il main aveva un Totale): **5**; hit rate: 80.0% (4/5 giudicate)

### (iii) Righe 1X2 gia' presenti

- nel main: 39; identiche nel branch (salvo rank, selector_version, calculation_id): **39**; diverse: 0; perse: 0

### Hit rate complessivo del Top Mix visibile

- prima (main): 73.4% su 79 giudicate (79 righe)
- dopo (branch): 78.4% su 51 giudicate (51 righe)

- controlli: branch con Totale = 0; 1X2 del main diventato Totale = 0; duplicati main/branch = 0/0

## Variante `legacy`

### (i) Totali del vecchio Top Mix

| mercato | nel main | sparite (nessun 1X2) | rivalutate su 1X2 |
|---|---:|---:|---:|
| OVER_2.5 | 7 | 5 | 2 |
| UNDER_2.5 | 13 | 12 | 1 |
| GG | 20 | 18 | 2 |
| NG | 0 | 0 | 0 |

### (ii) Partite che entrano con un 1X2

- nuove (il main non aveva nulla): **5**; hit rate: 100.0% (5/5 giudicate)
- rivalutate (il main aveva un Totale): **5**; hit rate: 60.0% (3/5 giudicate)

### (iii) Righe 1X2 gia' presenti

- nel main: 30; identiche nel branch (salvo rank, selector_version, calculation_id): **30**; diverse: 0; perse: 0

### Hit rate complessivo del Top Mix visibile

- prima (main): 75.7% su 70 giudicate (70 righe)
- dopo (branch): 82.5% su 40 giudicate (40 righe)

- controlli: branch con Totale = 0; 1X2 del main diventato Totale = 0; duplicati main/branch = 0/0

## Variante `totale`

### (i) Totali del vecchio Top Mix

| mercato | nel main | sparite (nessun 1X2) | rivalutate su 1X2 |
|---|---:|---:|---:|
| OVER_2.5 | 14 | 10 | 4 |
| UNDER_2.5 | 26 | 23 | 3 |
| GG | 40 | 37 | 3 |
| NG | 0 | 0 | 0 |

### (ii) Partite che entrano con un 1X2

- nuove (il main non aveva nulla): **12**; hit rate: 91.7% (11/12 giudicate)
- rivalutate (il main aveva un Totale): **10**; hit rate: 70.0% (7/10 giudicate)

### (iii) Righe 1X2 gia' presenti

- nel main: 69; identiche nel branch (salvo rank, selector_version, calculation_id): **69**; diverse: 0; perse: 0

### Hit rate complessivo del Top Mix visibile

- prima (main): 74.5% su 149 giudicate (149 righe)
- dopo (branch): 80.2% su 91 giudicate (91 righe)

- controlli: branch con Totale = 0; 1X2 del main diventato Totale = 0; duplicati main/branch = 0/0
