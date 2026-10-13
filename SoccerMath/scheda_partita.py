"""scheda_partita.py — la scheda partita in parole (modulo PURO, senza Streamlit).

COSA FA
-------
Per una partita in programma mette insieme, in parole semplici, i fatti che
servono a decidere una giocata: le probabilita' 1/X/2 delle quote (e quelle del
modello, quando il giro e' pronto), la classifica con la posta in palio delle
due squadre, la forma delle ultime 5 partite di campionato con la forza degli
avversari, i gol fatti e subiti, i precedenti stagionali.

La scheda NON produce numeri propri: nessun punteggio, nessun voto, nessun
indice. La probabilita' resta quella delle quote (stessa fonte e stesso formato
delle tabelle della scheda Giocate) e tutto il resto sono conteggi sui risultati
gia' archiviati.

FONTI (una sola per ciascun blocco, nessuna chiamata di rete)
-------------------------------------------------------------
* risultati della stagione in corso: il file ``<Prefisso>_Live.csv`` del
  campionato (stessa risoluzione di ``config``, nessuna lista a mano);
* forza delle squadre: l'Elo GIA' calcolato dall'app
  (``models/elo_engine.EloEngine.history``, l'unica sorgente del rating in app);
* probabilita' di mercato: ``live_odds.json`` (scritto dal workflow), letto con
  ``market_odds`` — le stesse funzioni della scheda Giocate;
* terna 1X2 del modello: mappa ``{(casa, trasferta): {"1","X","2"}}`` passata
  dal chiamante (in app e' quella del giro del modello, sola lettura).

REGOLE DI LETTURA (dichiarate nel referto, testate una per una)
---------------------------------------------------------------
* ``GIORNATE_MINIME_CLASSIFICA = 5``: prima di 5 giornate giocate la frase di
  classifica e' "Campionato appena iniziato: classifica ancora poco
  indicativa" (sotto le 5 giornate i punti non separano ancora le squadre);
* ``MIN_PARTITE_BLOCCO = 3``: un blocco con meno di 3 partite non mostra numeri,
  dichiara il dato insufficiente;
* ``MIN_PARTITE_PERCENTUALE = 5``: sotto 5 partite nessuna percentuale, solo
  "N su M partite";
* le distanze in classifica sono punti del riferimento MENO punti della
  squadra: positive = da recuperare, negative = di vantaggio;
* la zona retrocessione e' l'insieme delle ULTIME 3 posizioni; in Bundesliga e
  Ligue 1 (18 squadre) la terzultima e' la posizione di spareggio e viene
  scritta come tale (``LEGHE_CON_SPAREGGIO``);
* la forza dell'avversario e' a tre fasce ("forte", "media", "debole") sui
  TERZILI dell'Elo del campionato al momento della partita, letto PRIMA della
  partita (walk-forward: il rating di una partita futura non entra nella fascia
  di una partita passata).

Il modulo non importa streamlit: e' usabile da app, script di audit e test.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

import config
import lista_giocate as lg
import market_odds as mo
from display_names import display_name
from season_calendar import season_label, season_start_year_of
from team_aliases import clean_name
from team_names import resolve_team_name

SCHEDA_PARTITA_VERSION = "scheda_partita_v1"

# --- Regole dichiarate (referto: "Regole della scheda partita") -------------
GIORNATE_MINIME_CLASSIFICA = 5   # sotto 5 giornate giocate: frase "appena iniziato"
MIN_PARTITE_BLOCCO = 3           # sotto 3 partite: blocco "dati insufficienti"
MIN_PARTITE_PERCENTUALE = 5      # sotto 5 partite: mai una percentuale
SOGLIA_TITOLO = 6                # punti dal primo posto entro cui si e' "in corsa"
SOGLIA_EUROPA = 6                # punti dal sesto posto entro cui si e' "in corsa"
SOGLIA_SALVEZZA = 6              # punti sopra la zona entro cui la lotta e' aperta
ZONA_RETROCESSIONE = 3           # ultime N posizioni = zona retrocessione
LEGHE_CON_SPAREGGIO = ("Bundesliga", "Ligue 1")  # terzultima = spareggio
ELO_INIZIALE = 1500.0            # rating di partenza del motore Elo (nessuna partita)

FASCE_ELO = ("forte", "media", "debole")

FRASE_APPENA_INIZIATO = "Campionato appena iniziato: classifica ancora poco indicativa."

#: Nota dichiarata sui campionati a spareggio: la terzultima NON retrocede
#: direttamente. Si scrive SEMPRE che si parla della zona retrocessione in
#: Bundesliga e Ligue 1 (18 squadre), perche' li' la prima posizione della
#: zona e' lo spareggio e non la retrocessione.
NOTA_SPAREGGIO = " (terzultima = spareggio)"
FRASE_QUOTE_ASSENTI = "Quote non ancora disponibili"


# ---------------------------------------------------------------------------
# 0. Utilità di formato (stesse parole e stesso formato della scheda Giocate)
# ---------------------------------------------------------------------------
def percento_una_cifra(valore: Any) -> Optional[float]:
    """Probabilita' (0-1 oppure 0-100) -> percentuale con UNA cifra (numero).

    E' lo stesso numero delle colonne "Quote %"/"Modello %" della scheda
    Giocate (``app.percento_decimale``): una cifra decimale, ``None`` se non
    c'e' un numero. Nessuno zero inventato.
    """
    if valore is None or isinstance(valore, bool):
        return None
    try:
        v = float(valore)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    if v <= 1.0:
        v *= 100.0
    return round(v, 1)


def percento_in_parole(valore: Any) -> str:
    """Percentuale come si scrive in italiano: 45.3 -> "45,3%" (0-1 o 0-100)."""
    n = percento_una_cifra(valore)
    if n is None:
        return "n/d"
    return f"{n:.1f}".replace(".", ",") + "%"


def percento_numero_in_parole(numero: Any) -> str:
    """Percentuale GIA' in 0-100 (es. il "Modello %" del giro del modello)."""
    if numero is None or isinstance(numero, bool):
        return "n/d"
    try:
        v = float(numero)
    except (TypeError, ValueError):
        return "n/d"
    if not math.isfinite(v):
        return "n/d"
    return f"{v:.1f}".replace(".", ",") + "%"


def media_una_cifra(valore: Any) -> str:
    """Media gol in italiano: 1.666 -> "1,7"; None -> "n/d"."""
    if valore is None:
        return "n/d"
    try:
        v = float(valore)
    except (TypeError, ValueError):
        return "n/d"
    if not math.isfinite(v):
        return "n/d"
    return f"{v:.1f}".replace(".", ",")


def _punteggio(gol_casa: Any, gol_ospiti: Any) -> str:
    def n(x):
        try:
            return str(int(x))
        except (TypeError, ValueError):
            return "?"
    return f"{n(gol_casa)}-{n(gol_ospiti)}"


def chiave_partita_canonica(home: Any, away: Any) -> Optional[Tuple[str, str]]:
    """Coppia di nomi canonici dei due lati, o ``None`` se un nome non risolve.

    Stessa risoluzione della produzione (``team_names.resolve_team_name``,
    nessun fuzzy matching): la fonte quote e il calendario dicono la stessa
    squadra in modi diversi e questo e' l'unico punto in cui si decidono le
    chiavi. Un nome non riconosciuto NON viene indovinato.
    """
    h = resolve_team_name(home)
    a = resolve_team_name(away)
    if not (h.mapped and a.mapped):
        return None
    return (h.canonical, a.canonical)


# ---------------------------------------------------------------------------
# 1. Risultati della stagione in corso (fonte: <Prefisso>_Live.csv)
# ---------------------------------------------------------------------------
def percorso_live_csv(camp_key: str) -> Optional[str]:
    """Percorso del file Live del campionato, dalla config (nessuna lista a mano)."""
    info = config.get_league_config(camp_key) or {}
    percorso = info.get("live_csv")
    return str(percorso) if percorso else None


def carica_risultati_stagione(camp_key: str, stagione: Optional[int] = None,
                              percorso: Optional[str] = None) -> pd.DataFrame:
    """Le partite GIOCATE della stagione in corso, in ordine di data.

    Colonne: ``data`` (Timestamp, giorno), ``casa``/``trasferta`` (nomi
    canonici), ``gol_casa``/``gol_ospiti`` (interi), ``giornata`` (int o None),
    ``casa_display``/``trasferta_display`` (nomi da mostrare). Le righe senza
    risultato (``FTR`` mancante) restano fuori: la scheda parla di partite
    giocate.

    ``stagione`` e' l'anno di inizio (2026 = 2026/2027); il filtro usa
    ``season_calendar``, il confine unico del progetto. Un file assente o
    illeggibile da' un DataFrame vuoto (il chiamante lo dichiara), mai
    un'eccezione.
    """
    percorso = percorso or percorso_live_csv(camp_key)
    vuoto = pd.DataFrame(columns=["data", "casa", "trasferta", "gol_casa",
                                  "gol_ospiti", "giornata", "casa_display",
                                  "trasferta_display"])
    if not percorso or not os.path.exists(percorso):
        return vuoto
    try:
        df = pd.read_csv(percorso, low_memory=False)
    except Exception:
        return vuoto
    if df.empty or not {"Date", "HomeTeam", "AwayTeam", "FTR"}.issubset(df.columns):
        return vuoto
    df = df.copy()
    df["data"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    df = df.dropna(subset=["data", "HomeTeam", "AwayTeam"])
    df = df[df["FTR"].notna()]
    anno = int(stagione if stagione is not None else config.get_current_season_start_year())
    df = df[df["data"].apply(lambda d: season_start_year_of(d) == anno)]
    if df.empty:
        return vuoto
    out = pd.DataFrame({
        "data": df["data"].dt.normalize(),
        "casa": df["HomeTeam"].apply(clean_name),
        "trasferta": df["AwayTeam"].apply(clean_name),
        "gol_casa": pd.to_numeric(df["FTHG"], errors="coerce"),
        "gol_ospiti": pd.to_numeric(df["FTAG"], errors="coerce"),
        "giornata": (pd.to_numeric(df["Matchday"], errors="coerce")
                     if "Matchday" in df.columns else None),
    })
    out["casa_display"] = out["casa"].apply(display_name)
    out["trasferta_display"] = out["trasferta"].apply(display_name)
    out = out.dropna(subset=["gol_casa", "gol_ospiti"])
    out["gol_casa"] = out["gol_casa"].astype(int)
    out["gol_ospiti"] = out["gol_ospiti"].astype(int)
    out = out.sort_values("data", kind="stable").reset_index(drop=True)
    return out


def numero_squadre(camp_key: str, stagione: Optional[int] = None,
                   risultati: Optional[pd.DataFrame] = None) -> Optional[int]:
    """Quante squadre ha il campionato della stagione (18 o 20 nelle 5 leghe).

    Prima fonte: il roster di calendario versionato
    (``database/season_rosters.json``, la stessa informazione di calendario del
    motore Elo: nota prima del via, non un risultato). Se il roster della
    stagione non c'e', si contano le squadre comparse nei risultati; se non
    c'e' nemmeno quella, ``None`` (il chiamante dichiara il dato mancante).
    """
    anno = int(stagione if stagione is not None else config.get_current_season_start_year())
    try:
        percorso = os.path.join(str(config.DATABASE_DIR), "season_rosters.json")
        with open(percorso, "r", encoding="utf-8") as fh:
            roster = json.load(fh)
        squadre = (roster.get(camp_key) or {}).get(str(anno))
        if squadre:
            return len(squadre)
    except Exception:
        pass
    if risultati is not None and not risultati.empty:
        return len(set(risultati["casa"]) | set(risultati["trasferta"]))
    return None


def giornate_totali(n_squadre: int) -> int:
    """Giornate di un campionato a ``n_squadre``: andata e ritorno (38 o 34)."""
    return 2 * (int(n_squadre) - 1)


def giornate_rimaste(n_squadre: int, partite_giocate: int) -> int:
    """Giornate che restano a una squadra con ``partite_giocate`` giocate."""
    return max(0, giornate_totali(n_squadre) - int(partite_giocate))


# ---------------------------------------------------------------------------
# 2. Classifica (dai soli risultati della stagione) e posta in palio
# ---------------------------------------------------------------------------
def classifica(risultati: pd.DataFrame) -> List[Dict[str, Any]]:
    """Classifica della stagione dai risultati, una riga per squadra.

    Ordinamento: punti, differenza reti, gol fatti, nome (crescente). E' lo
    stesso criterio di lettura della classifica reale; le squadre a pari
    merito sono ordinate per nome, cosi' il risultato e' deterministico.
    """
    if risultati is None or risultati.empty:
        return []
    righe: Dict[str, Dict[str, Any]] = {}

    def _riga(team: str) -> Dict[str, Any]:
        if team not in righe:
            righe[team] = {"squadra": team, "nome": display_name(team), "punti": 0,
                           "giocate": 0, "vinte": 0, "pari": 0, "perse": 0,
                           "gf": 0, "gs": 0}
        return righe[team]

    for _, m in risultati.iterrows():
        h, a = m["casa"], m["trasferta"]
        gh, ga = int(m["gol_casa"]), int(m["gol_ospiti"])
        rh, ra = _riga(h), _riga(a)
        rh["giocate"] += 1
        ra["giocate"] += 1
        rh["gf"] += gh
        rh["gs"] += ga
        ra["gf"] += ga
        ra["gs"] += gh
        if gh > ga:
            rh["punti"] += 3
            rh["vinte"] += 1
            ra["perse"] += 1
        elif gh < ga:
            ra["punti"] += 3
            ra["vinte"] += 1
            rh["perse"] += 1
        else:
            rh["punti"] += 1
            ra["punti"] += 1
            rh["pari"] += 1
            ra["pari"] += 1
    elenco = list(righe.values())
    for r in elenco:
        r["dr"] = r["gf"] - r["gs"]
    elenco.sort(key=lambda r: (-r["punti"], -r["dr"], -r["gf"], r["squadra"]))
    for i, r in enumerate(elenco, start=1):
        r["pos"] = i
    return elenco


def riga_classifica(cl: Sequence[Dict[str, Any]], squadra: str) -> Optional[Dict[str, Any]]:
    """La riga di ``squadra`` (nome canonico) nella classifica, o ``None``."""
    for r in cl or []:
        if r.get("squadra") == squadra:
            return r
    return None


def posizione_zero(camp_key: str, n_squadre: int) -> int:
    """Prima posizione della zona retrocessione: ultime 3 posizioni."""
    return max(1, int(n_squadre) - (ZONA_RETROCESSIONE - 1))


def e_zona_spareggio(camp_key: str, pos: int, n_squadre: int) -> bool:
    """True se ``pos`` e' la terzultima di un campionato con lo spareggio."""
    return (camp_key in LEGHE_CON_SPAREGGIO
            and int(n_squadre) == 18
            and int(pos) == int(n_squadre) - 2)


def posta_in_palio(cl: Sequence[Dict[str, Any]], camp_key: str, squadra: str,
                   n_squadre: int) -> Optional[Dict[str, Any]]:
    """Distanze in punti e posta in palio di una squadra.

    Le distanze sono PUNTI DEL RIFERIMENTO MENO PUNTI DELLA SQUADRA: positive =
    da recuperare, negative = di vantaggio.

    * ``dal_primo``        0 per la prima in classifica;
    * ``dal_quarto``/``dal_sesto``  quarto e sesto posto;
    * ``dalla_zona``       punti SOPRA la prima posizione della zona
                           retrocessione (negativa = dentro la zona);
    * ``in_zona``          True se la squadra e' nelle ultime 3 posizioni;
    * ``spareggio``        True se e' la terzultima in un campionato a 18.
    """
    riga = riga_classifica(cl, squadra)
    if riga is None or n_squadre is None:
        return None
    pos_zona = posizione_zero(camp_key, n_squadre)
    zona = next((r for r in cl if r["pos"] == pos_zona), None)
    # Prima posizione di retrocessione DIRETTA: la successiva alla prima della
    # zona. Nei campionati a spareggio (Bundesliga, Ligue 1) la terzultima e'
    # lo spareggio, quindi la retrocessione diretta comincia dalla penultima.
    diretta = next((r for r in cl if r["pos"] == pos_zona + 1), None)
    primo = next((r for r in cl if r["pos"] == 1), None)
    quarto = next((r for r in cl if r["pos"] == 4), None)
    sesto = next((r for r in cl if r["pos"] == 6), None)
    return {
        "pos": riga["pos"], "punti": riga["punti"], "giocate": riga["giocate"],
        "vinte": riga["vinte"], "pari": riga["pari"], "perse": riga["perse"],
        "gf": riga["gf"], "gs": riga["gs"], "dr": riga["dr"],
        "giornate_rimaste": giornate_rimaste(n_squadre, riga["giocate"]),
        "dal_primo": (primo["punti"] - riga["punti"]) if primo else None,
        "dal_quarto": (quarto["punti"] - riga["punti"]) if quarto else None,
        "dal_sesto": (sesto["punti"] - riga["punti"]) if sesto else None,
        "dalla_zona": (riga["punti"] - zona["punti"]) if zona else None,
        "dalla_retrocessione_diretta": ((riga["punti"] - diretta["punti"])
                                        if diretta else None),
        "in_zona": bool(riga["pos"] >= pos_zona),
        "spareggio": e_zona_spareggio(camp_key, riga["pos"], n_squadre),
        "n_squadre": int(n_squadre),
    }


def _punti(n: Any) -> str:
    try:
        v = int(n)
    except (TypeError, ValueError):
        return "n/d"
    return f"{v} punto" if v == 1 else f"{v} punti"


def _distanza_in_parole(distanza: int, riferimento: str) -> str:
    """Distanza in punti da una posizione: "a 5 punti dal sesto posto" / "5 sopra"."""
    if distanza is None:
        return "distanza non disponibile"
    if distanza > 0:
        return f"a {_punti(distanza)} dal {riferimento}"
    if distanza == 0:
        return f"appaiata al {riferimento}"
    return f"{_punti(-distanza)} sopra il {riferimento}"


def frase_obiettivi(p: Optional[Dict[str, Any]], giornate_giocate: int,
                    camp_key: str) -> str:
    """La frase che dice cosa si sta giocando la squadra, da regole esplicite.

    Implementa, nell'ordine (la prima che vale vince):

    1. meno di ``GIORNATE_MINIME_CLASSIFICA`` giornate giocate ->
       "Campionato appena iniziato: classifica ancora poco indicativa";
    2. a 0 punti dal primo posto -> "Al comando della classifica";
       entro ``SOGLIA_TITOLO`` -> "In corsa per il titolo: N punti dal primo posto";
    3. nelle ultime 3 posizioni -> dentro la zona ("... dentro la zona
       retrocessione"), oppure la frase dello spareggio se e' la terzultima di
       un campionato a 18 squadre ("Spareggio: terzultima, ...");
    4. entro ``SOGLIA_SALVEZZA`` punti sopra la zona -> "Lotta per non
       retrocedere: N punti sopra la zona" (a 0 punti: "appaiata alla zona");
    5. sesto posto raggiunto o superato -> "In zona Europa: ...";
       entro ``SOGLIA_EUROPA`` punti dal sesto -> "In corsa per l'Europa: N
       punti dal sesto posto";
    6. altrimenti -> "Zona tranquilla: N punti dal sesto posto, M sopra la zona
       retrocessione".
    """
    if p is None:
        return "Classifica non disponibile: dati di questa stagione insufficienti."
    if giornate_giocate < GIORNATE_MINIME_CLASSIFICA:
        return FRASE_APPENA_INIZIATO
    d_primo, d_sesto, dalla_zona = p.get("dal_primo"), p.get("dal_sesto"), p.get("dalla_zona")
    if d_primo is not None and d_primo <= 0:
        return "Al comando della classifica."
    if d_primo is not None and d_primo <= SOGLIA_TITOLO:
        return f"In corsa per il titolo: {_punti(d_primo)} dal primo posto."
    nota = (NOTA_SPAREGGIO if camp_key in LEGHE_CON_SPAREGGIO
            and int(p.get("n_squadre") or 0) == 18 else "")
    if p.get("in_zona"):
        if p.get("spareggio"):
            # Terzultima di un campionato a spareggio: la distanza che conta e'
            # quella dalla retrocessione DIRETTA (la penultima), perche' la
            # prima posizione della zona e' la sua.
            diretta = p.get("dalla_retrocessione_diretta")
            if diretta is None:
                return "Spareggio: terzultima, posizione di spareggio."
            if diretta > 0:
                return f"Spareggio: terzultima, {_punti(diretta)} sopra la retrocessione diretta."
            if diretta == 0:
                return "Spareggio: terzultima, appaiata alla retrocessione diretta."
            return f"Spareggio: terzultima, {_punti(-diretta)} dentro la retrocessione diretta."
        return ("Lotta per non retrocedere: " + _punti(abs(dalla_zona or 0))
                + " dentro la zona retrocessione" + nota + ".")
    if dalla_zona is not None and dalla_zona <= SOGLIA_SALVEZZA:
        if dalla_zona <= 0:
            return ("Lotta per non retrocedere: appaiata alla zona retrocessione"
                    + nota + ".")
        return (f"Lotta per non retrocedere: {_punti(dalla_zona)} sopra la zona"
                + nota + ".")
    if d_sesto is not None and d_sesto <= 0:
        if d_sesto == 0:
            return "In zona Europa: al sesto posto."
        return f"In zona Europa: {_punti(-d_sesto)} sopra il sesto posto."
    if d_sesto is not None and d_sesto <= SOGLIA_EUROPA:
        return f"In corsa per l'Europa: {_punti(d_sesto)} dal sesto posto."
    return (f"Zona tranquilla: {_punti(d_sesto)} dal sesto posto, "
            f"{_punti(dalla_zona)} sopra la zona retrocessione" + nota + "."
            if d_sesto is not None and dalla_zona is not None
            else "Classifica non disponibile: dati di questa stagione insufficienti.")


# ---------------------------------------------------------------------------
# 3. Forza Elo nel tempo (walk-forward) e fasce dell'avversario
# ---------------------------------------------------------------------------
def storico_elo_da_engine(engine: Any) -> Dict[str, List[Dict[str, Any]]]:
    """Storia Elo per squadra dall'engine di produzione, in ordine di data.

    Per ogni partita: ``data`` (giorno), ``elo_prima`` e ``elo_dopo``. E' la
    stessa storia che il motore usa per la propria classifica: la scheda non
    ricalcola nessun rating.
    """
    out: Dict[str, List[Dict[str, Any]]] = {}
    history = getattr(engine, "history", None) or {}
    for squadra, eventi in history.items():
        righe = []
        for e in eventi or []:
            data = pd.Timestamp(e.get("date")).normalize()
            righe.append({"data": data,
                          "elo_prima": float(e.get("elo_before", ELO_INIZIALE)),
                          "elo_dopo": float(e.get("elo_after", ELO_INIZIALE))})
        righe.sort(key=lambda r: r["data"])
        out[squadra] = righe
    return out


def fotografia_elo(storico: Dict[str, List[Dict[str, Any]]],
                   istante: Any) -> Dict[str, float]:
    """I rating di TUTTE le squadre PRIMA di ``istante`` (giorno incluso: no).

    Per ogni squadra si prende l'ultimo ``elo_dopo`` di una partita con data
    STRETTAMENTE precedente a ``istante``; una squadra che non ha ancora
    giocato vale ``ELO_INIZIALE`` (1500, il punto di partenza del motore).
    E' l'unica lettura ammessa per la forza degli avversari: il risultato della
    partita di ``istante`` non puo' entrare nella fotografia.
    """
    giorno = pd.Timestamp(istante).normalize()
    foto: Dict[str, float] = {}
    for squadra, righe in (storico or {}).items():
        valore = ELO_INIZIALE
        for r in righe:
            if r["data"] < giorno:
                valore = r["elo_dopo"]
            else:
                break
        foto[squadra] = valore
    return foto


def fotografie_delle_date(storico: Dict[str, List[Dict[str, Any]]],
                          date: Iterable[Any]) -> Dict[pd.Timestamp, Dict[str, float]]:
    """Fotografia Elo per OGNI giorno richiesto (una volta per giorno)."""
    fuori: Dict[pd.Timestamp, Dict[str, float]] = {}
    for d in sorted({pd.Timestamp(x).normalize() for x in date}):
        fuori[d] = fotografia_elo(storico, d)
    return fuori


def fasce_elo(fotografia: Dict[str, float]) -> Dict[str, str]:
    """Fasce "forte", "media", "debole" sui TERZILI dell'Elo del campionato.

    Le squadre si ordinano per rating (a pari rating, per nome: deterministico)
    e si tagliano in tre gruppi il piu' uguali possibile: il primo terzo e'
    "debole", l'ultimo "forte". Con meno di 3 squadre non si formano fasce
    (dizionario vuoto: il chiamante dichiara il dato insufficiente).
    """
    if not fotografia or len(fotografia) < 3:
        return {}
    ordinati = sorted(fotografia.items(), key=lambda kv: (kv[1], kv[0]))
    n = len(ordinati)
    taglio = math.ceil(n / 3.0)
    fuori: Dict[str, str] = {}
    for i, (squadra, _rating) in enumerate(ordinati):
        if i < taglio:
            banda = "debole"
        elif i >= n - taglio:
            banda = "forte"
        else:
            banda = "media"
        fuori[squadra] = banda
    return fuori


def banda_avversario(fasce: Dict[str, str], avversario: str) -> Optional[str]:
    """La fascia di ``avversario`` (o ``None`` se non e' nella fotografia)."""
    return (fasce or {}).get(avversario)


# ---------------------------------------------------------------------------
# 4. Forma: ultime 5 partite di campionato con la forza dell'avversario
# ---------------------------------------------------------------------------
def forma_recente(risultati: pd.DataFrame, squadra: str,
                  fotografie: Dict[pd.Timestamp, Dict[str, float]],
                  n: int = 5) -> Dict[str, Any]:
    """Ultime ``n`` partite di campionato di ``squadra`` nella stagione.

    Ogni partita porta risultato (dal punto di vista della squadra), casa o
    trasferta e la fascia dell'avversario calcolata con l'Elo PRIMA di quella
    partita. Con meno di ``MIN_PARTITE_BLOCCO`` partite il blocco e' dichiarato
    insufficiente (``sufficiente=False``) e non si contano medie.
    """
    vuoto = {"partite": [], "n": 0, "vinte": 0, "pari": 0, "perse": 0,
             "vittorie_contro_deboli": 0, "vittorie_contro_forti": 0,
             "sufficiente": False, "squadra": squadra, "nome": display_name(squadra)}
    if risultati is None or risultati.empty:
        return vuoto
    righe = []
    for _, m in risultati.iterrows():
        if m["casa"] == squadra:
            righe.append({"data": m["data"], "casa": True, "avversario": m["trasferta"],
                          "fatti": int(m["gol_casa"]), "subiti": int(m["gol_ospiti"])})
        elif m["trasferta"] == squadra:
            righe.append({"data": m["data"], "casa": False, "avversario": m["casa"],
                          "fatti": int(m["gol_ospiti"]), "subiti": int(m["gol_casa"])})
    righe.sort(key=lambda r: r["data"])
    ultime = righe[-int(n):] if n else righe
    out = dict(vuoto)
    out["n"] = len(righe)
    out["sufficiente"] = len(righe) >= MIN_PARTITE_BLOCCO
    for r in ultime:
        esito = "V" if r["fatti"] > r["subiti"] else ("P" if r["fatti"] < r["subiti"] else "X")
        foto = (fotografie or {}).get(pd.Timestamp(r["data"]).normalize()) or {}
        banda = banda_avversario(fasce_elo(foto), r["avversario"])
        out["partite"].append({
            "data": r["data"], "dove": "in casa" if r["casa"] else "in trasferta",
            "avversario": r["avversario"], "avversario_nome": display_name(r["avversario"]),
            "risultato": _punteggio(r["fatti"], r["subiti"]),
            "risultato_esteso": f"{r['fatti']}-{r['subiti']}",
            "esito": esito, "banda_avversario": banda,
        })
        if esito == "V":
            out["vinte"] += 1
            if banda == "debole":
                out["vittorie_contro_deboli"] += 1
            elif banda == "forte":
                out["vittorie_contro_forti"] += 1
        elif esito == "X":
            out["pari"] += 1
        else:
            out["perse"] += 1
    return out


def testo_forma(forma: Dict[str, Any]) -> str:
    """La riga riassuntiva della forma: "Ultime 5: 3 vinte, 1 pari, 1 persa; ...".

    Con meno di ``MIN_PARTITE_BLOCCO`` partite la riga dichiara il dato
    insufficiente invece di contare su un campione vuoto.
    """
    if not forma or not forma.get("partite"):
        return ("Dati insufficienti: nessuna partita di campionato giocata "
                "in questa stagione.")
    if not forma.get("sufficiente"):
        return (f"Dati insufficienti: solo {forma['n']} "
                f"{'partita giocata' if forma['n'] == 1 else 'partite giocate'} "
                "in questo campionato.")
    frase = (f"Ultime {len(forma['partite'])}: "
             f"{forma['vinte']} {'vinta' if forma['vinte'] == 1 else 'vinte'}, "
             f"{forma['pari']} pari, "
             f"{forma['perse']} {'persa' if forma['perse'] == 1 else 'perse'}")
    deboli = forma.get("vittorie_contro_deboli") or 0
    if deboli:
        frase += (f"; {'1 delle vittorie' if deboli == 1 else str(deboli) + ' delle vittorie'}"
                  " contro squadre deboli")
    return frase + "."


# ---------------------------------------------------------------------------
# 5. Gol: stagione, casa/trasferta, partite "su giocate"
# ---------------------------------------------------------------------------
def _blocco_gol(righe: Sequence[Dict[str, int]]) -> Dict[str, Any]:
    n = len(righe)
    if n == 0:
        return {"partite": 0, "fatti": 0, "subiti": 0, "media_fatti": None,
                "media_subiti": None, "entrambe_a_segno": 0, "piu_di_2_gol": 0,
                "senza_subire": 0}
    fatti = sum(r["fatti"] for r in righe)
    subiti = sum(r["subiti"] for r in righe)
    return {
        "partite": n, "fatti": fatti, "subiti": subiti,
        "media_fatti": fatti / n, "media_subiti": subiti / n,
        "entrambe_a_segno": sum(1 for r in righe if r["fatti"] > 0 and r["subiti"] > 0),
        "piu_di_2_gol": sum(1 for r in righe if (r["fatti"] + r["subiti"]) > 2),
        "senza_subire": sum(1 for r in righe if r["subiti"] == 0),
    }


def statistiche_gol(risultati: pd.DataFrame, squadra: str) -> Dict[str, Any]:
    """Gol fatti e subiti della squadra: stagione, in casa, in trasferta.

    Sempre ``N su M partite`` per i conteggi; le medie solo con almeno
    ``MIN_PARTITE_BLOCCO`` partite (altrimenti ``None``: nessun numero su un
    campione vuoto).
    """
    vuoto = {"stagione": _blocco_gol([]), "casa": _blocco_gol([]),
             "trasferta": _blocco_gol([]), "sufficiente": False,
             "squadra": squadra, "nome": display_name(squadra)}
    if risultati is None or risultati.empty:
        return vuoto
    tutte, in_casa, fuori = [], [], []
    for _, m in risultati.iterrows():
        if m["casa"] == squadra:
            r = {"fatti": int(m["gol_casa"]), "subiti": int(m["gol_ospiti"])}
            tutte.append(r)
            in_casa.append(r)
        elif m["trasferta"] == squadra:
            r = {"fatti": int(m["gol_ospiti"]), "subiti": int(m["gol_casa"])}
            tutte.append(r)
            fuori.append(r)
    if not tutte:
        return vuoto
    sufficiente = len(tutte) >= MIN_PARTITE_BLOCCO
    out = {"stagione": _blocco_gol(tutte), "casa": _blocco_gol(in_casa),
           "trasferta": _blocco_gol(fuori), "sufficiente": sufficiente,
           "squadra": squadra, "nome": display_name(squadra)}
    if not sufficiente:
        for chiave in ("stagione", "casa", "trasferta"):
            out[chiave] = dict(out[chiave])
            out[chiave]["media_fatti"] = None
            out[chiave]["media_subiti"] = None
    return out


def conteggio_in_parole(conteggio: int, partite: int) -> str:
    """Conteggio sempre come "N su M partite", percentuale solo da 5 partite.

    Sotto ``MIN_PARTITE_PERCENTUALE`` partite la percentuale NON si scrive (su
    tre partite "33%" sembra un dato e non lo e'): resta il conteggio.
    """
    base = f"{int(conteggio)} su {int(partite)} partite"
    if partite >= MIN_PARTITE_PERCENTUALE and partite > 0:
        base += f" ({conteggio / partite * 100:.0f}%)"
    return base


def testo_gol(gol: Dict[str, Any]) -> List[str]:
    """Le righe del blocco gol, in parole (una voce per riga)."""
    if not gol or not gol.get("stagione", {}).get("partite"):
        return ["Dati insufficienti: nessuna partita di campionato giocata "
                "in questa stagione."]
    stag, casa, fuori = gol["stagione"], gol["casa"], gol["trasferta"]
    righe = []
    if not gol.get("sufficiente"):
        # Meno di tre partite: le medie non si calcolano e la riga lo dice,
        # invece di mostrare "n/d" che sembra un dato mancante qualunque. I
        # conteggi restano, sempre nella forma "N su M partite".
        righe.append(
            f"Dati insufficienti: solo {stag['partite']} "
            + ("partita giocata" if stag["partite"] == 1 else "partite giocate")
            + " in questo campionato: le medie dei gol non si calcolano.")
    else:
        righe.append(f"In stagione: {media_una_cifra(stag['media_fatti'])} gol fatti e "
                     f"{media_una_cifra(stag['media_subiti'])} subiti a partita "
                     f"({stag['partite']} partite).")
        if casa["partite"]:
            righe.append(f"In casa: {media_una_cifra(casa['media_fatti'])} fatti e "
                         f"{media_una_cifra(casa['media_subiti'])} subiti a partita "
                         f"({casa['partite']} partite).")
        if fuori["partite"]:
            righe.append(f"In trasferta: {media_una_cifra(fuori['media_fatti'])} fatti e "
                         f"{media_una_cifra(fuori['media_subiti'])} subiti a partita "
                         f"({fuori['partite']} partite).")
    righe.append("Partite con entrambe a segno: "
                 + conteggio_in_parole(stag["entrambe_a_segno"], stag["partite"]) + ".")
    righe.append("Partite con più di 2 gol: "
                 + conteggio_in_parole(stag["piu_di_2_gol"], stag["partite"]) + ".")
    righe.append("Partite senza subire gol: "
                 + conteggio_in_parole(stag["senza_subire"], stag["partite"]) + ".")
    return righe


# ---------------------------------------------------------------------------
# 6. Precedenti stagionali
# ---------------------------------------------------------------------------
def precedenti_stagionali(risultati: pd.DataFrame, squadra_a: str,
                          squadra_b: str) -> List[Dict[str, Any]]:
    """Gli incroci GIA' giocati in questa stagione fra le due squadre."""
    fuori: List[Dict[str, Any]] = []
    if risultati is None or risultati.empty:
        return fuori
    for _, m in risultati.iterrows():
        coppia = {m["casa"], m["trasferta"]}
        if coppia == {squadra_a, squadra_b}:
            fuori.append({
                "data": m["data"],
                "casa": m["casa"], "trasferta": m["trasferta"],
                "casa_nome": display_name(m["casa"]),
                "trasferta_nome": display_name(m["trasferta"]),
                "risultato": _punteggio(m["gol_casa"], m["gol_ospiti"]),
                "giornata": (int(m["giornata"]) if pd.notna(m.get("giornata")) else None),
            })
    fuori.sort(key=lambda r: r["data"])
    return fuori


# ---------------------------------------------------------------------------
# 7. Probabilita' 1/X/2: quote (e modello) per la partita della scheda
# ---------------------------------------------------------------------------
def evento_di(payload: Optional[Dict[str, Any]], home: Any, away: Any,
              kickoff: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """L'evento della fonte quote per la partita, o ``None`` se non c'e'."""
    if not payload:
        return None
    indice = mo.indice_partite(payload)["indice"]
    return mo.cerca_quote(indice, home, away, kickoff)


def probabilita_di(evento: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Probabilita' e quota 1/X/2 dell'evento (stessa de-vig della scheda Giocate).

    Ritorna ``{"disponibile": False}`` quando le quote non ci sono o non sono
    valide: la scheda scrive "Quote non ancora disponibili", nessun numero
    inventato.
    """
    if not evento:
        return {"disponibile": False, "quote": None, "quota": None, "fonte": None,
                "n_libri": 0}
    mkt = mo.probabilita_mercato(evento.get("libri") or [])
    probs = mkt.get("probs")
    if not probs or any(probs.get(e) is None for e in ("1", "X", "2")):
        return {"disponibile": False, "quote": None, "quota": None,
                "fonte": mkt.get("fonte"), "n_libri": mkt.get("n_libri") or 0}
    return {"disponibile": True, "quote": probs, "quota": mkt.get("odds"),
            "fonte": mkt.get("fonte"), "n_libri": mkt.get("n_libri") or 0}


def etichetta_esito(esito: str, casa_nome: str, trasferta_nome: str) -> str:
    """L'esito 1/X/2 in parole: "Vince Inter", "Pareggio", "Vince Roma"."""
    return lg.giocata_in_parole(esito, casa_nome, trasferta_nome)


def modello_per_esito(mappa_1x2: Optional[Dict[Any, Any]], casa: Any, away: Any,
                      esito: str) -> Optional[float]:
    """Percentuale del modello per l'esito, dalla mappa del giro del modello.

    La chiave e' la coppia canonica (casa, trasferta): un nome non risolto o
    una partita non coperta dal giro valgono ``None`` (cella vuota, nessuno
    zero inventato).
    """
    chiave = chiave_partita_canonica(casa, away)
    if chiave is None or not isinstance(mappa_1x2, dict):
        # Non-dict (per esempio le LETTURE del giro del modello al posto della
        # mappa per partita): non e' una terna, si scrive "non disponibile".
        # E' la stessa regola della cella vuota, senza eccezioni a schermo.
        return None
    terna = mappa_1x2.get(chiave)
    if not isinstance(terna, dict):
        return None
    valore = terna.get(str(esito))
    if valore is None or isinstance(valore, bool):
        return None
    try:
        v = float(valore)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def probabilita_in_parole(probs: Optional[Dict[str, Any]], casa_nome: str,
                          trasferta_nome: str) -> str:
    """La riga 1/X/2 in parole: "Vince Inter 45,3% · Pareggio 28,0% · Vince Roma 26,7%"."""
    if not probs:
        return FRASE_QUOTE_ASSENTI
    pezzi = []
    for esito in ("1", "X", "2"):
        valore = probs.get(esito)
        if valore is None:
            return FRASE_QUOTE_ASSENTI
        pezzi.append(f"{etichetta_esito(esito, casa_nome, trasferta_nome)} "
                     f"{percento_in_parole(valore)}")
    return " · ".join(pezzi)


# ---------------------------------------------------------------------------
# 8. Abbinamento delle partite in programma ai nomi dei CSV
# ---------------------------------------------------------------------------
def partite_in_programma(payload: Optional[Dict[str, Any]],
                         adesso: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Gli eventi della fonte quote NON ancora iniziati, in ordine di orario."""
    if not payload:
        return []
    now = adesso or mo._adesso_utc()
    fuori = []
    for ev in mo.eventi_quote(payload):
        dt = lg.parse_commence_time(ev.get("commence_time"))
        if dt is not None and dt <= now:
            continue
        fuori.append(ev)
    fuori.sort(key=lambda e: (e.get("commence_time") or "", e.get("lega") or ""))
    return fuori


def abbina_partite(payload: Optional[Dict[str, Any]], adesso: Optional[datetime] = None,
                   per_lega: Optional[Dict[str, Iterable[str]]] = None
                   ) -> Dict[str, Any]:
    """Abbina le partite in programma ai nomi dei CSV, dichiarando le mancanti.

    ``per_lega`` = {lega: insieme dei nomi canonici presenti nei risultati
    della lega}. Una partita "trova corrispondenza" quando ENTRAMBI i nomi
    risolvono a un nome canonico (``team_names``) e quel nome esiste nei
    risultati della sua lega: nessun abbinamento per somiglianza.

    Ritorna ``{"partite": [...], "n": int, "n_abbinate": int, "n_non_abbinate":
    int, "non_abbinate": [{lega, casa, trasferta, casa_canonica, ...}]}``.
    """
    elenco = partite_in_programma(payload, adesso)
    abbinate, non_abbinate = [], []
    for ev in elenco:
        lega = ev.get("lega") or "?"
        casa_raw, trasferta_raw = ev.get("home_team"), ev.get("away_team")
        h, a = resolve_team_name(casa_raw), resolve_team_name(trasferta_raw)
        noti = set(per_lega.get(lega) or []) if per_lega else None
        ok = h.mapped and a.mapped and (noti is None or (h.canonical in noti and a.canonical in noti))
        record = {
            "lega": lega, "id": ev.get("id"), "kickoff_utc": ev.get("commence_time"),
            "casa": casa_raw, "trasferta": trasferta_raw,
            "casa_canonica": h.canonical, "trasferta_canonica": a.canonical,
            "casa_nome": display_name(h.canonical) if h.mapped else (casa_raw or "?"),
            "trasferta_nome": display_name(a.canonical) if a.mapped else (trasferta_raw or "?"),
            "quando": lg.quando_italiano(ev.get("commence_time")),
            "abbinata": bool(ok),
            "motivo": None if ok else (
                "nome squadra non riconosciuto" if not (h.mapped and a.mapped)
                else "squadra fuori dai risultati della lega"),
        }
        (abbinate if ok else non_abbinate).append(record)
    return {"partite": abbinate, "tutte": abbinate + non_abbinate,
            "n": len(elenco), "n_abbinate": len(abbinate),
            "n_non_abbinate": len(non_abbinate), "non_abbinate": non_abbinate}


# ---------------------------------------------------------------------------
# 9. La scheda della partita
# ---------------------------------------------------------------------------
def costruisci_scheda(camp_key: str, casa: Any, trasferta: Any, *,
                      kickoff_utc: Optional[str] = None,
                      evento_quote: Optional[Dict[str, Any]] = None,
                      payload_quote: Optional[Dict[str, Any]] = None,
                      modello_1x2: Optional[Dict[Any, Any]] = None,
                      risultati: Optional[pd.DataFrame] = None,
                      storico_elo: Optional[Dict[str, List[Dict[str, Any]]]] = None,
                      stagione: Optional[int] = None,
                      giornate_giocate: Optional[int] = None) -> Dict[str, Any]:
    """La scheda completa di una partita, dalla sola lettura dei dati locali.

    ``casa``/``trasferta`` sono i nomi come arrivano (quote o calendario): la
    chiave canonica la decide ``resolve_team_name``. ``risultati`` e
    ``storico_elo`` si possono passare gia' pronti (AppTest e test): il modulo
    legge da solo solo se non li riceve.
    """
    chiave = chiave_partita_canonica(casa, trasferta)
    casa_can = chiave[0] if chiave else None
    trasferta_can = chiave[1] if chiave else None
    casa_nome = display_name(casa_can) if casa_can else (str(casa) if casa else "?")
    trasferta_nome = (display_name(trasferta_can) if trasferta_can
                      else (str(trasferta) if trasferta else "?"))

    if risultati is None:
        risultati = carica_risultati_stagione(camp_key, stagione=stagione)
    if storico_elo is None:
        try:  # import locale: la scheda non pesa su chi non la usa
            from models.elo_engine import get_elo_engine
            storico_elo = storico_elo_da_engine(get_elo_engine(camp_key))
        except Exception:
            storico_elo = {}

    scheda: Dict[str, Any] = {
        "versione": SCHEDA_PARTITA_VERSION,
        "lega": camp_key,
        "casa": {"grezzo": casa, "canonica": casa_can, "nome": casa_nome},
        "trasferta": {"grezzo": trasferta, "canonica": trasferta_can, "nome": trasferta_nome},
        "kickoff_utc": kickoff_utc or (evento_quote or {}).get("commence_time"),
        "risultati_disponibili": bool(risultati is not None and not risultati.empty),
        "elo_disponibile": bool(storico_elo),
    }
    scheda["quando"] = lg.quando_italiano(scheda["kickoff_utc"]) if scheda["kickoff_utc"] else "data n/d"

    # --- (a) probabilita' delle quote e del modello ------------------------
    evento = evento_quote
    if evento is None and payload_quote:
        evento = evento_di(payload_quote, casa, trasferta, scheda["kickoff_utc"])
    prob = probabilita_di(evento)
    terna_modello = {}
    for esito in ("1", "X", "2"):
        terna_modello[esito] = modello_per_esito(modello_1x2, casa, trasferta, esito)
    scheda["probabilita"] = {
        **prob,
        "modello": terna_modello,
        "modello_disponibile": any(v is not None for v in terna_modello.values()),
        "in_parole": probabilita_in_parole(prob.get("quote"), casa_nome, trasferta_nome),
    }

    # --- (b) classifica e obiettivi ---------------------------------------
    cl = classifica(risultati)
    n_squadre = numero_squadre(camp_key, stagione=stagione, risultati=risultati)
    if giornate_giocate is None:
        giornate_giocate = (max((r["giocate"] for r in cl), default=0) if cl else 0)
    blocchi = {}
    for ruolo, canonica in (("casa", casa_can), ("trasferta", trasferta_can)):
        if canonica is None:
            blocchi[ruolo] = None
            continue
        dati = posta_in_palio(cl, camp_key, canonica, n_squadre) if n_squadre else None
        if dati is not None:
            dati = dict(dati)
            dati["nome"] = display_name(canonica)
            dati["frase"] = frase_obiettivi(dati, giornate_giocate, camp_key)
        blocchi[ruolo] = dati
    scheda["classifica"] = {
        "n_squadre": n_squadre,
        "giornate_totali": giornate_totali(n_squadre) if n_squadre else None,
        "giornate_giocate": giornate_giocate,
        "casa": blocchi["casa"], "trasferta": blocchi["trasferta"],
        "disponibile": bool(blocchi["casa"] or blocchi["trasferta"]),
    }

    # --- (c) forma: ultime 5 partite, con la forza degli avversari ---------
    date_stagione = list(risultati["data"]) if risultati is not None and not risultati.empty else []
    fotografie = fotografie_delle_date(storico_elo, date_stagione) if storico_elo else {}
    scheda["forma"] = {
        "casa": forma_recente(risultati, casa_can, fotografie) if casa_can else None,
        "trasferta": forma_recente(risultati, trasferta_can, fotografie) if trasferta_can else None,
        "elo_disponibile": bool(storico_elo),
    }

    # --- (d) gol -----------------------------------------------------------
    scheda["gol"] = {
        "casa": statistiche_gol(risultati, casa_can) if casa_can else None,
        "trasferta": statistiche_gol(risultati, trasferta_can) if trasferta_can else None,
    }

    # --- (e) precedenti stagionali ----------------------------------------
    scheda["precedenti"] = (precedenti_stagionali(risultati, casa_can, trasferta_can)
                            if casa_can and trasferta_can else [])

    # --- (f) note sui dati mancanti ---------------------------------------
    note = []
    if not scheda["risultati_disponibili"]:
        note.append("Risultati di questa stagione non disponibili per il campionato.")
    if not scheda["elo_disponibile"]:
        note.append("Forza delle squadre (rating) non disponibile: le fasce degli "
                    "avversari non si possono calcolare.")
    if chiave is None:
        note.append("Nome squadra non riconosciuto: la scheda resta senza i dati di "
                    "quella squadra.")
    scheda["note_dati"] = note
    return scheda


def blocchi_scheda(scheda: Dict[str, Any]) -> List[Tuple[str, List[str]]]:
    """La scheda in blocchi pronti da mostrare: ``[(titolo, [righe...]), ...]``.

    E' l'unico punto in cui i numeri diventano frasi: app.py si limita a
    disegnare i blocchi, e i test possono leggerli o confrontarli senza
    passare dall'interfaccia.
    """
    fuori: List[Tuple[str, List[str]]] = []
    casa, trasferta = scheda["casa"]["nome"], scheda["trasferta"]["nome"]

    # (a) probabilita'
    prob = scheda["probabilita"]
    righe = []
    if prob.get("disponibile"):
        for esito in ("1", "X", "2"):
            etichetta = etichette_probabilita(esito, casa, trasferta)
            valore = percento_in_parole(prob["quote"].get(esito))
            modello = prob["modello"].get(esito)
            modello_txt = (percento_numero_in_parole(modello)
                           if modello is not None else "non disponibile")
            righe.append(f"{etichetta}: Quote % {valore} · Modello % {modello_txt}")
    else:
        righe.append(FRASE_QUOTE_ASSENTI)
    fuori.append(("Probabilità (dalle quote dei bookmaker)", righe))

    # (b) classifica e obiettivi
    righe = []
    for ruolo, nome in (("casa", casa), ("trasferta", trasferta)):
        dati = (scheda.get("classifica") or {}).get(ruolo)
        if not dati:
            righe.append(f"{nome}: dati di classifica insufficienti per questa stagione.")
            continue
        pezzi = [f"{dati['pos']}° posto", f"{dati['punti']} punti",
                 f"{dati['giocate']} partite giocate"]
        if (scheda["classifica"] or {}).get("n_squadre"):
            rimaste = giornate_rimaste(scheda["classifica"]["n_squadre"], dati["giocate"])
            pezzi.append(f"{rimaste} giornate rimaste")
        if dati.get("dal_primo") is not None:
            pezzi.append(_distanza_in_parole(dati["dal_primo"], "primo posto"))
        if dati.get("dal_quarto") is not None:
            pezzi.append(_distanza_in_parole(dati["dal_quarto"], "quarto posto"))
        if dati.get("dal_sesto") is not None:
            pezzi.append(_distanza_in_parole(dati["dal_sesto"], "sesto posto"))
        if dati.get("dalla_zona") is not None:
            z = dati["dalla_zona"]
            if z > 0:
                pezzi.append(f"{_punti(z)} sopra la zona retrocessione")
            elif z == 0:
                pezzi.append("appaiata alla zona retrocessione")
            else:
                pezzi.append(f"{_punti(abs(z))} dentro la zona retrocessione")
        if dati.get("spareggio"):
            pezzi.append("terzultima = spareggio")
            d = dati.get("dalla_retrocessione_diretta")
            if d is not None:
                if d > 0:
                    pezzi.append(f"{_punti(d)} sopra la retrocessione diretta")
                elif d == 0:
                    pezzi.append("appaiata alla retrocessione diretta")
                else:
                    pezzi.append(f"{_punti(abs(d))} dentro la retrocessione diretta")
        righe.append(f"{nome}: " + ", ".join(pezzi) + ".")
        righe.append(f"{nome}: {dati['frase']}")
    fuori.append(("Classifica e obiettivi", righe))

    # (c) forma
    righe = []
    for ruolo, nome in (("casa", casa), ("trasferta", trasferta)):
        forma = (scheda.get("forma") or {}).get(ruolo)
        if not forma:
            righe.append(f"{nome}: dati di forma insufficienti.")
            continue
        righe.append(f"{nome} — {testo_forma(forma)}")
        for p in forma.get("partite", []):
            banda = p.get("banda_avversario") or "fascia non disponibile"
            righe.append(f"  · {p['data'].strftime('%d/%m')} {p['dove']} con "
                         f"{p['avversario_nome']}: {p['risultato']} ({p['esito']}) "
                         f"— avversario {banda}")
    fuori.append(("Forma: ultime 5 partite di campionato", righe))

    # (d) gol
    righe = []
    for ruolo, nome in (("casa", casa), ("trasferta", trasferta)):
        gol = (scheda.get("gol") or {}).get(ruolo)
        if not gol:
            righe.append(f"{nome}: dati sui gol insufficienti.")
            continue
        righe.append(f"{nome}:")
        righe.extend("  · " + r for r in testo_gol(gol))
    fuori.append(("Gol", righe))

    # (e) precedenti
    righe = []
    for p in scheda.get("precedenti") or []:
        giornata = f" (giornata {p['giornata']})" if p.get("giornata") else ""
        righe.append(f"{p['casa_nome']} - {p['trasferta_nome']} {p['risultato']} "
                     f"il {p['data'].strftime('%d/%m')}{giornata}")
    if not righe:
        righe.append("Le due squadre non si sono ancora affrontate in questa stagione.")
    fuori.append(("Precedenti stagionali", righe))

    # (f) note sui dati mancanti
    if scheda.get("note_dati"):
        fuori.append(("Dati mancanti", list(scheda["note_dati"])))
    return fuori


def etichette_probabilita(esito: str, casa: str, trasferta: str) -> str:
    """L'esito 1/X/2 con la sigla: "1 (Vince Inter)", "X (Pareggio)", ..."""
    parole = lg.giocata_in_parole(esito, casa, trasferta)
    return f"{esito} ({parole})"


def testo_scheda(scheda: Dict[str, Any]) -> str:
    """La scheda intera come testo (usata dai referti e dai test di parole)."""
    intestazione = (f"{scheda['casa']['nome']} - {scheda['trasferta']['nome']} · "
                    f"{scheda['quando']} · {scheda['lega']}")
    righe = [intestazione, ""]
    for titolo, contenuto in blocchi_scheda(scheda):
        righe.append(titolo)
        righe.extend(contenuto)
        righe.append("")
    return "\n".join(righe).rstrip() + "\n"


def righe_partite_giornata(matches: Sequence[Dict[str, Any]],
                           payload_quote: Optional[Dict[str, Any]],
                           adesso: Optional[datetime] = None,
                           per_lega: Optional[Dict[str, Iterable[str]]] = None
                           ) -> List[Dict[str, Any]]:
    """L'elenco della scheda Partite: una riga per partita della giornata.

    Ogni riga porta i nomi da mostrare, la data e l'ora italiane e la
    probabilita' 1/X/2 in parole quando la fonte quote ha quella partita (per
    la lega giusta: due campionati diversi possono avere partite omonime).
    """
    indice = mo.indice_partite(payload_quote)["indice"] if payload_quote else {}
    fuori = []
    for m in matches or []:
        lega = m.get("lega")
        casa_raw, trasferta_raw = m.get("casa"), m.get("trasferta")
        casa_can = clean_name(casa_raw) if casa_raw else None
        trasferta_can = clean_name(trasferta_raw) if trasferta_raw else None
        casa_disp = display_name(casa_can) if casa_can else "?"
        trasferta_disp = display_name(trasferta_can) if trasferta_can else "?"
        evento = mo.cerca_quote(indice, casa_raw, trasferta_raw, m.get("utcDate")) if indice else None
        if evento is not None and lega and evento.get("lega") and evento.get("lega") != lega:
            evento = None  # lega diversa: non e' la quota di questa partita
        prob = probabilita_di(evento)
        fuori.append({
            "lega": lega, "casa": casa_raw, "trasferta": trasferta_raw,
            "casa_canonica": casa_can, "trasferta_canonica": trasferta_can,
            "casa_nome": casa_disp, "trasferta_nome": trasferta_disp,
            "utcDate": m.get("utcDate"),
            "quando": lg.quando_italiano(m.get("utcDate")) if m.get("utcDate") else "data n/d",
            "probabilita": prob,
            "in_parole": probabilita_in_parole(prob.get("quote"), casa_disp, trasferta_disp),
        })
    return fuori
