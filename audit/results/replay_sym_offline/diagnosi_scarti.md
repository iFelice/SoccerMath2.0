# Perche' le partite coperte da un solo modello non sono un buco

Ogni riga nasce da un click VERO all'istante kickoff - 1 s: gli ingressi del selettore
sono quelli intercettati mentre il click girava, non un ricalcolo a parte.

| partita | campione | modello presente | modello assente | motivo dell'assenza |
|---|---|---|---|---|
| Aston Villa - Arsenal (Premier League, 2026-08-31T19:00:00Z) | -31199 | Attuale: 2 56.3% (soglia 55.0%, disaccordo 10.0%) | Legacy: 2 52.7% | **sotto soglia (0.527 < 0.55)** (P 63.8%, E 49.1%, disaccordo 14.7%, soglia 55.0%) |
| Betis - Real Madrid (La Liga, 2026-09-04T19:00:00Z) | -30801 | Attuale: 2 55.3% (soglia 55.0%, disaccordo 11.4%) | Legacy: 2 51.9% | **sotto soglia (0.519 < 0.55)** (P 63.9%, E 47.9%, disaccordo 16.0%, soglia 55.0%) |
| Ipswich - Liverpool (Premier League, 2026-09-04T19:00:00Z) | -31200 | Attuale: 2 71.4% (soglia 55.0%, disaccordo 23.1%) | Legacy: 2 63.0% | **veto (disaccordo >= 0,25)** (P 88.7%, E 54.5%, disaccordo 34.2%, soglia 55.0%) |
| Werder Bremen - Leipzig (Bundesliga, 2026-09-05T13:30:00Z) | -32256 | Attuale: 2 57.6% (soglia 55.0%, disaccordo 11.8%) | Legacy: 2 54.5% | **sotto soglia (0.545 < 0.55)** (P 66.5%, E 50.5%, disaccordo 16.0%, soglia 55.0%) |
| Freiburg - Borussia Mönchengladbach (Bundesliga, 2026-09-12T13:30:00Z) | -32264 | Attuale: 1 60.3% (soglia 55.0%, disaccordo 12.8%) | Legacy: 1 52.5% | **sotto soglia (0.525 < 0.55)** (P 70.0%, E 46.7%, disaccordo 23.3%, soglia 55.0%) |
| Real Madrid - Vallecano (La Liga, 2026-09-12T19:00:00Z) | -30816 | Attuale: 1 77.9% (soglia 55.0%, disaccordo 14.4%) | Legacy: 1 67.7% | **veto (disaccordo >= 0,25)** (P 88.7%, E 60.8%, disaccordo 27.9%, soglia 55.0%) |
| Torino - Roma (Serie A, 2026-09-14T16:30:00Z) | -31594 | Attuale: 2 63.3% (soglia 55.0%, disaccordo 8.5%) | Legacy: 2 54.0% | **sotto soglia (0.540 < 0.55)** (P 69.7%, E 48.8%, disaccordo 20.8%, soglia 55.0%) |
| Elche - Real Madrid (La Liga, 2026-09-15T19:30:00Z) | -30825 | Attuale: 2 76.2% (soglia 55.0%, disaccordo 11.6%) | Legacy: 2 66.0% | **veto (disaccordo >= 0,25)** (P 84.9%, E 59.7%, disaccordo 25.2%, soglia 55.0%) |
| Nottingham Forest - Coventry City (Premier League, 2026-09-19T16:30:00Z) | -31227 | Attuale: 1 58.8% (soglia 55.0%, disaccordo 11.8%) | Legacy: 1 54.8% | **sotto soglia (0.548 < 0.55)** (P 67.7%, E 50.4%, disaccordo 17.3%, soglia 55.0%) |

Riepilogo: sotto soglia: 6 · veto: 3.

Conseguenza: nessuna riga viene inventata per far coincidere i campioni. Le soglie
(0,55 1X2 / 0,60 Totali) e il veto restano quelli di produzione, e per il modello
assente il Registro non ha nulla da scrivere perche' quel modello, su quella partita,
non ha espresso una scelta.
