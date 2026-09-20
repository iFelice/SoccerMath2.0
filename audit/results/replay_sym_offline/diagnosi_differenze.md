# Perché 9 partite hanno il modello Attuale ma non il Legacy

Replay offline (fixture dai CSV/archivio) sulla finestra **2026-08-30 → 2026-09-20**:
92 click scrivibili, 70 righe Attuale, 61 righe Legacy, 61 partite con ENTRAMBI i
modelli, **9 partite coperte solo dal modello Attuale**, 0 solo dal Legacy.

Le 9 partite non sono un buco: sono scartate da una REGOLA del selettore
(`seleziona_riga_top_mix`, soglie 0,55 1X2 / 0,60 Totali e veto di disaccordo
|P-E| < 0,25), applicata allo stesso Poisson con l'Elo legacy. Verificate una
per una sui dati reali dello snapshot del loro kickoff:

| partita | lega | mercato | P (Poisson) | E attuale | E legacy | conf attuale | conf legacy | esito del legacy |
|---|---|---|---|---|---|---|---|---|
| Real Madrid - Vallecano | La Liga | 1 | 0.892 | 0.759 | 0.626 | 0.792 | 0.693 | **veto**: disaccordo 0.266 ≥ 0.25 |
| Torino - Roma | Serie A | 2 | 0.706 | 0.595 | 0.472 | 0.623 | 0.530 | **sotto soglia** (0.530 < 0.55) |
| Freiburg - M'gladbach | Bundesliga | 1 | 0.725 | 0.599 | 0.491 | 0.631 | 0.549 | **sotto soglia** (0.549 < 0.55) |

Le altre sei (Betis-Real Madrid, Elche-Real Madrid, Aston Villa-Arsenal,
Ipswich-Liverpool, Nottingham Forest-Coventry, Werder Bremen-Leipzig) seguono
lo stesso schema: l'Elo legacy, che porta il boost xG retroattivo, si allontana
dal Poisson più dell'Elo attuale — quindi o supera il veto di disaccordo o
porta la confidence appena sotto la soglia.

Direzione misurata: **il legacy non copre MAI una partita che l'attuale non
copra** (0 casi su 61+9). È l'atteso: l'Elo legacy è più "rumoroso" e il veto
lo colpisce più spesso.

Conseguenza per la commessa: "stesso campione, stessa lunghezza per entrambi"
si realizza sulle 61 partite che ENTRAMBI i modelli giocano; le altre 9 hanno
per il legacy una NON-scelta, che il Registro giustamente non inventa. I
conteggi sono nel referto (`## Copertura per modello`) e verificabili in sola
lettura con `SoccerMath/registry_coverage_check.py`.
