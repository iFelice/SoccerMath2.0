# Scheda partita — testo reso (prodotto dall'AppTest, non scritto a mano)

Questo file lo scrive il test `SoccerMath/test_apptest_scheda_partita.py` quando
la variabile d'ambiente `SCHEDA_RENDER_OUT` punta a questo percorso: il testo
sotto e' **il markdown reso dal riquadro aperto in AppTest**, copiato cosi'
com'e' (`_testo_riquadro`), non ricomposto a mano. Le due partite sono del
prossimo turno sulla fixture pinnata (`snapshot_reale()`, 90 eventi, orologio
congelato a venerdi' 2026-10-16 18:00 ora italiana):

* **vertice**: Bologna - Inter (Serie A) — 14ª in classifica contro la prima;
* **bassa classifica**: Le Havre - Auxerre (Ligue 1) — 18ª contro 16ª.

Comando che l'ha prodotto (l'unica cosa che scrive il file e' il test):

```
cd SoccerMath && SCHEDA_RENDER_OUT=../audit/results/scheda_partita_render.md \
  python -m pytest test_apptest_scheda_partita.py -q
# 4 passed, 68 subtests passed
```

Sotto, il testo reso. In vista non compaiono parole vietate (punto 6 della
PR #64): lo stesso test lo verifica con `PAROLE_VIETATE` su questo testo.

## vertice: Bologna - Inter (Serie A)

```
### Bologna - Inter
##### Probabilità (dalle quote dei bookmaker)
1 (Vince Bologna): Quote % 17,4% · Modello % 18,3%
X (Pareggio): Quote % 24,3% · Modello % 17,5%
2 (Vince Inter): Quote % 58,4% · Modello % 64,2%
##### Classifica e obiettivi
Bologna: 14° posto, 5 punti, 6 partite giocate, 32 giornate rimaste, a 11 punti dal primo posto, a 8 punti dal quarto posto, a 6 punti dal sesto posto, 1 punto sopra la zona retrocessione.
Bologna: Lotta per non retrocedere: 1 punto sopra la zona.
Inter: 1° posto, 16 punti, 6 partite giocate, 32 giornate rimaste, appaiata al primo posto, 3 punti sopra il quarto posto, 5 punti sopra il sesto posto, 12 punti sopra la zona retrocessione.
Inter: Al comando della classifica.
##### Forma: ultime 5 partite di campionato
Bologna — Ultime 5: 1 vinta, 2 pari, 2 perse; 1 delle vittorie contro squadre deboli.
· 31/08 in trasferta con Atalanta: 0-1 (P) — avversario forte
· 06/09 in casa con Sassuolo: 2-2 (X) — avversario media
· 13/09 in trasferta con Napoli: 0-1 (P) — avversario forte
· 19/09 in casa con Torino: 1-1 (X) — avversario media
· 11/10 in trasferta con Lecce: 2-1 (V) — avversario debole
Inter — Ultime 5: 4 vinte, 1 pari, 0 perse.
· 30/08 in trasferta con Cagliari: 1-0 (V) — avversario media
· 05/09 in casa con Napoli: 3-2 (V) — avversario forte
· 14/09 in casa con Udinese: 5-3 (V) — avversario media
· 19/09 in trasferta con Roma: 2-2 (X) — avversario forte
· 10/10 in casa con Parma: 3-0 (V) — avversario media
##### Gol
Bologna:
· In stagione: 0,8 gol fatti e 1,2 subiti a partita (6 partite).
· In casa: 1,0 fatti e 1,3 subiti a partita (3 partite).
· In trasferta: 0,7 fatti e 1,0 subiti a partita (3 partite).
· Partite con entrambe a segno: 3 su 6 partite (50%).
· Partite con più di 2 gol: 2 su 6 partite (33%).
· Partite senza subire gol: 0 su 6 partite (0%).
Inter:
· In stagione: 3,0 gol fatti e 1,3 subiti a partita (6 partite).
· In casa: 3,8 fatti e 1,5 subiti a partita (4 partite).
· In trasferta: 1,5 fatti e 1,0 subiti a partita (2 partite).
· Partite con entrambe a segno: 4 su 6 partite (67%).
· Partite con più di 2 gol: 5 su 6 partite (83%).
· Partite senza subire gol: 2 su 6 partite (33%).
##### Precedenti stagionali
Le due squadre non si sono ancora affrontate in questa stagione.
```

## bassa: Le Havre - Auxerre (Ligue 1)

```
### Le Havre - Auxerre
##### Probabilità (dalle quote dei bookmaker)
1 (Vince Le Havre): Quote % 38,3% · Modello % 39,0%
X (Pareggio): Quote % 28,4% · Modello % 26,7%
2 (Vince Auxerre): Quote % 33,3% · Modello % 34,4%
##### Classifica e obiettivi
Le Havre: 18° posto, 2 punti, 6 partite giocate, 28 giornate rimaste, a 12 punti dal primo posto, a 9 punti dal quarto posto, a 9 punti dal sesto posto, 4 punti dentro la zona retrocessione.
Le Havre: Lotta per non retrocedere: 4 punti dentro la zona retrocessione (terzultima = spareggio).
Auxerre: 16° posto, 6 punti, 6 partite giocate, 28 giornate rimaste, a 8 punti dal primo posto, a 5 punti dal quarto posto, a 5 punti dal sesto posto, appaiata alla zona retrocessione, terzultima = spareggio, 2 punti sopra la retrocessione diretta.
Auxerre: Spareggio: terzultima, 2 punti sopra la retrocessione diretta.
##### Forma: ultime 5 partite di campionato
Le Havre — Ultime 5: 0 vinte, 2 pari, 3 perse.
· 29/08 in trasferta con Lyon: 1-1 (X) — avversario forte
· 05/09 in casa con Brest: 1-2 (P) — avversario media
· 12/09 in casa con Angers: 0-0 (X) — avversario debole
· 19/09 in trasferta con Toulouse: 2-3 (P) — avversario media
· 10/10 in trasferta con Lille: 0-1 (P) — avversario forte
Auxerre — Ultime 5: 2 vinte, 0 pari, 3 perse.
· 29/08 in casa con Angers: 1-3 (P) — avversario debole
· 04/09 in trasferta con Lyon: 1-3 (P) — avversario forte
· 12/09 in casa con Nice: 1-0 (V) — avversario media
· 20/09 in casa con Brest: 2-1 (V) — avversario media
· 11/10 in trasferta con Rennes: 1-4 (P) — avversario forte
##### Gol
Le Havre:
· In stagione: 0,7 gol fatti e 1,3 subiti a partita (6 partite).
· In casa: 0,3 fatti e 1,0 subiti a partita (3 partite).
· In trasferta: 1,0 fatti e 1,7 subiti a partita (3 partite).
· Partite con entrambe a segno: 3 su 6 partite (50%).
· Partite con più di 2 gol: 2 su 6 partite (33%).
· Partite senza subire gol: 1 su 6 partite (17%).
Auxerre:
· In stagione: 1,3 gol fatti e 2,7 subiti a partita (6 partite).
· In casa: 1,3 fatti e 1,3 subiti a partita (3 partite).
· In trasferta: 1,3 fatti e 4,0 subiti a partita (3 partite).
· Partite con entrambe a segno: 5 su 6 partite (83%).
· Partite con più di 2 gol: 5 su 6 partite (83%).
· Partite senza subire gol: 1 su 6 partite (17%).
##### Precedenti stagionali
Le due squadre non si sono ancora affrontate in questa stagione.
```

