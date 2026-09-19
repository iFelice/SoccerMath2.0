"""
display_names.py - Nomi squadra SOLO per la visualizzazione (DISPLAY_NAME_MAP).

Terzo livello di nomi, VOLONTARIAMENTE separato dai due di calcolo
(``team_aliases.TEAM_NAME_MAP`` e ``team_aliases.UNDERSTAT_NAME_MAP``):
quelle due tabelle restano l'unico posto dove si decide come un nome grezzo
diventa la CHIAVE con cui motore/Elo/classifiche indicizzano le squadre, e
non vengono toccate da questo modulo in nessun verso. ``DISPLAY_NAME_MAP``
serve solo a cio' che l'utente vede sullo schermo.

Problema misurato (stagione 2026/27, fonti: righe grezze nei ``*_Live.csv``
scritte prima degli alias, alias documentati in ``TEAM_NAME_MAP`` e
``audit/results/schalke_bayern_921.json``): l'interfaccia mostra gli
``shortName`` GREZZI dell'API football-data.org, e alcuni sono brutti,
troncati o ambigui:

    "Atleti" (Atletico Madrid), "Barça", "Athletic" (Athletic Bilbao),
    "Brighton Hove", "Nottingham" (Nottingham Forest), "HSV" (Hamburg),
    "Schalke", "Bremen" (Werder Bremen), "Frankfurt" (Eintracht Frankfurt),
    "Stade Rennais" (Rennes), "Olympique Lyon", "Paris" (Paris FC, non PSG!)

Disegno:

  * le CHIAVI sono i nomi CANONICI (``clean_name`` dei CSV football-data):
    ``display_name()`` risolve qualunque forma grezza attraverso
    ``clean_name`` -- la STESSA garanzia che gia' vale per i lookup del
    motore -- e cosi' la mappa e' immune a quale variante esatta
    (shortName, name lungo, forma accentata) restituisce l'API;
  * i VALORI sono i nomi da mostrare; per le squadre dove il nome canonico
    e' gia' il nome giusto la voce e' identita' e serve solo a normalizzare
    la variante grezza ("Barça" -> "Barcelona");
  * se un nome non risolve a nessuna chiave (squadra fuori tabella, nuova
    promossa, nome lungo mai visto) ``display_name`` lo restituisce
    IMMUTATO: il comportamento resta quello di oggi, nessun guess.

Invarianti (verificati in ``SoccerMath/test_display_names.py``):

  * ogni chiave e' gia' canonica: ``clean_name(chiave) == chiave``;
  * ``clean_name`` NON impara nulla da qui: ``clean_name("Atleti")`` resta
    "Ath Madrid" e ``clean_name("Atletico Madrid")`` resta "Atletico Madrid"
    (il nome display NON e' una chiave di matching);
  * questo modulo non viene importato da ``team_aliases``/``config``: la
    catena del calcolo non dipende dal display;
  * i punti di applicazione sono SOLO di visualizzazione (app.py:
    stringa ultimi risultati, righe/etichette Top Mix, Analisi Rapida,
    card PARTITE); i punti di confronto/chiave ricevono sempre il nome
    grezzo.
"""

from __future__ import annotations

from team_aliases import clean_name


# ==========================================
# Nomi display: canonico -> mostrato
# ==========================================
# Chiavi = nomi canonici (le stesse chiavi del motore). Voci identita'
# ("Barcelona": "Barcelona") esistono apposta: normalizzano la variante
# grezza dell'API al nome corretto. Elenco completo delle 96 squadre
# 2026/27 (con le forme grezze misurate) in
# audit/results/display_name_map_referto.md.
DISPLAY_NAME_MAP = {
    # --- Premier League -----------------------------------------------------
    # l'API mostra "Brighton Hove" (troncato)
    "Brighton": "Brighton",
    # l'API mostra "Nottingham" (solo citta')
    "Nott'm Forest": "Nottingham Forest",

    # --- La Liga ------------------------------------------------------------
    # l'API mostra "Atleti"
    "Ath Madrid": "Atletico Madrid",
    # l'API mostra "Athletic" (solo citta')
    "Ath Bilbao": "Athletic Bilbao",
    # l'API mostra "Barça"
    "Barcelona": "Barcelona",
    # l'API mostra "Santander" (solo citta': il club e' il Racing)
    "Santander": "Racing Santander",

    # --- Bundesliga ---------------------------------------------------------
    # l'API mostra "HSV" (sigla)
    "Hamburg": "Hamburg",
    # l'API mostra "Schalke"
    "Schalke 04": "Schalke 04",
    # l'API mostra "Bremen" (solo citta')
    "Werder Bremen": "Werder Bremen",
    # l'API mostra "Frankfurt" (solo citta'); anche il canonico e' brutto
    "Ein Frankfurt": "Eintracht Frankfurt",
    # l'API mostra "M'gladbach" (apostrofo del CSV football-data)
    "M'gladbach": "Borussia Mönchengladbach",

    # --- Ligue 1 ------------------------------------------------------------
    # l'API mostra "Stade Rennais"
    "Rennes": "Rennes",
    # l'API mostra "Olympique Lyon"
    "Lyon": "Lyon",
    # l'API mostra "Paris" per il Paris FC: AMBIGUO rispetto al PSG
    "Paris": "Paris FC",

    # --- Serie A ------------------------------------------------------------
    # Nessuna voce: i 20 shortName della Serie A 2026/27 sono gia' nomi
    # completi e leggibili (misurato in audit/results/display_name_map_referto.md).
}


def display_name(name: str) -> str:
    """Nome SOLO display di una squadra; mai usato come chiave di calcolo.

    Risolve ``name`` al nome canonico con ``clean_name`` (stessa risoluzione
    dei lookup del motore) e lo traduce nel nome da mostrare. Se il nome non
    corrisponde a nessuna voce, viene restituito IMMUTATO: nessun fuzzy
    matching, nessun guess -- esattamente il comportamento pre-esistente.

    Punti d'uso (solo visualizzazione, vedi il docstring del modulo):
    stringa ultimi risultati, righe/etichette Top Mix, Analisi Rapida e
    card PARTITE in ``app.py``.
    """
    if not name:
        return ""
    return DISPLAY_NAME_MAP.get(clean_name(name), name)
