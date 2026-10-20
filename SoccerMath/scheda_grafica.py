"""scheda_grafica.py — la scheda partita in HTML (modulo PURO, senza Streamlit).

COSA FA
-------
Riceve il dizionario prodotto da ``scheda_partita.costruisci_scheda`` e
restituisce STRINGHE HTML per due sezioni della scheda: le probabilita'
1/X/2 (barre) e la classifica delle due squadre (riquadri affiancati).
Nessuna chiamata a Streamlit, nessuna rete, nessun calcolo nuovo: i numeri
sono quelli che la scheda porta gia' (quote, modello, totals, distanze di
classifica), qui diventano solo HTML.

REGOLE
------
* ``tema`` sceglie la palette: ``"chiaro"`` (predefinita) o ``"scuro"``,
  dalla costante :data:`PALETTE`; un tema non riconosciuto ricade sulla
  palette chiara. I colori delle barre 1/X/2 sono fissi per esito
  (blu, grigio, arancione), in entrambe le palette.
* Ogni nome di squadra e ogni testo che arriva dai dati passa da
  ``html.escape`` prima di entrare nell'HTML: un nome con ``<`` o ``>``
  viene mostrato come testo, mai interpretato come un tag.
* Un dato che non c'e' non diventa mai la scritta ``None``/``nan``:
  o la riga non si mostra (le probabilita' del modello, solo se
  disponibili), o si scrive ``n/d``.
* La riga del modello mostra le percentuali come interi
  (``Modello: 1 31 X 27 2 42``), come nell'esempio della scheda.
* Il pronostico e' quello della scheda (``scheda["pronostico"]``, la
  stessa regola del Top Mix): la sigla se c'e', altrimenti il trattino
  con la nota che nessun esito arriva al 57 per cento (la soglia di
  ``market_odds.SOGLIA_TOPMIX_MERCATO``).
* I due riquadri di classifica stanno in una griglia CSS
  ``repeat(auto-fit, minmax(280px, 1fr))`` e sotto i 640 pixel di
  larghezza vanno uno sotto l'altro (media query esplicita).

Il modulo importa solo la libreria standard: e' usabile da app, test e
script senza trascinarsi dietro pandas o Streamlit.
"""
from __future__ import annotations

import html
import math
from typing import Any, Dict, List, Optional

# --- Palette (due varianti: chiara e scura) --------------------------------
PALETTE: Dict[str, Dict[str, str]] = {
    "chiaro": {
        "sfondo": "#ffffff",
        "testo": "#1a1d23",
        "bordo": "#d7dce2",
        "attenuato": "#68707c",
        "traccia": "#e7ebef",
        "riquadro": "#f7f8fa",
        "frase_sfondo": "#e9f1fd",
        "etichetta_sfondo": "#eef1f4",
        "accento": "#2563eb",
    },
    "scuro": {
        "sfondo": "#262730",
        "testo": "#fafafa",
        "bordo": "#454b57",
        "attenuato": "#b9bfca",
        "traccia": "#3a404c",
        "riquadro": "#1b1e26",
        "frase_sfondo": "#253a5c",
        "etichetta_sfondo": "#343a47",
        "accento": "#7aa8ff",
    },
}

#: Alias accettati per il parametro ``tema`` (le chiavi di PALETTE restano
#: la fonte: chi non e' in questa mappa e non e' una chiave ricade su
#: ``"chiaro"``).
_ALIAS_TEMI = {"light": "chiaro", "dark": "scuro"}

#: Colori fissi delle barre per esito: blu per l'1, grigio per la X,
#: arancione per il 2 (in entrambe le palette).
COLORI_ESITI = {"1": "#2563eb", "X": "#8a8f98", "2": "#e07b1f"}

#: Colori della freccia di classifica: verde se la posizione e' migliorata,
#: rosso se e' peggiorata, grigio se e' ferma.
COLORI_FRECCIA = {"su": "#1e9e4a", "giu": "#d63a2f", "ferma": "#7a828e"}

ESITI = ("1", "X", "2")

#: La soglia del pronostico mostrata nella nota (market_odds:
#: SOGLIA_TOPMIX_MERCATO = 0.57). E' solo il testo della nota: la scelta
#: dell'esito resta quella gia' fatta da scheda_partita.
NOTA_SOTTO_SOGLIA = "nessun esito arriva al 57 per cento"

FRASE_QUOTE_ASSENTI = "Quote non ancora disponibili"


# ---------------------------------------------------------------------------
# Utilita' (numeri dai dati: mai None/nan a schermo)
# ---------------------------------------------------------------------------
def _esc(testo: Any) -> str:
    """Testo dai dati -> HTML sicuro, con ``html.escape``.

    ``quote=False``: nessun dato finisce dentro un attributo (tutti i
    valori degli attributi sono costanti del modulo), quindi bastano
    ``<``, ``>`` e ``&`` escapati, e gli apostrofi delle frasi italiane
    restano leggibili nel sorgente (``l'Europa``, non ``l&#x27;Europa``).
    """
    return html.escape("" if testo is None else str(testo), quote=False)


def _numero(valore: Any) -> Optional[float]:
    """Un numero finito dai dati, o ``None`` (bool e non-numeri esclusi)."""
    if valore is None or isinstance(valore, bool):
        return None
    try:
        v = float(valore)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _percentuale(valore: Any) -> Optional[float]:
    """Probabilita' (0-1, o gia' 0-100) -> percentuale 0-100, o ``None``."""
    v = _numero(valore)
    if v is None:
        return None
    if v <= 1.0:
        v *= 100.0
    return min(100.0, max(0.0, v))


def _fmt_percentuale(pct: Optional[float]) -> str:
    """Percentuale con una cifra e la virgola italiana: 34.6 -> "34,6%"."""
    if pct is None:
        return "n/d"
    return f"{pct:.1f}".replace(".", ",") + "%"


def _fmt_modello(valore: Any) -> str:
    """Percentuale del modello come intero se e' intera: 31.0 -> "31".

    I valori del modello nella scheda sono GIA' percentuali (0-100, come
    li legge ``scheda_partita.numero_percentuale_modello``): qui non si
    riscalano, si scrivono senza decimali inutili (31, non 31,0).
    """
    v = _numero(valore)
    if v is None:
        return "n/d"
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:.1f}".replace(".", ",")


def _intero(valore: Any) -> Optional[int]:
    v = _numero(valore)
    return int(v) if v is not None else None


def _fmt_intero(valore: Any) -> str:
    n = _intero(valore)
    return str(n) if n is not None else "n/d"


def _punti(n: int) -> str:
    return f"{n} punto" if n == 1 else f"{n} punti"


def palette_di(tema: Optional[str] = "chiaro") -> Dict[str, str]:
    """La palette del tema ("chiaro"/"scuro", alias light/dark)."""
    chiave = _ALIAS_TEMI.get(str(tema or "").strip().lower(),
                             str(tema or "").strip().lower())
    return PALETTE.get(chiave, PALETTE["chiaro"])


def _stile(p: Dict[str, str]) -> str:
    """Il foglio di stile della scheda, con i colori della palette scelta."""
    return f"""<style>
.sg {{ --sg-sfondo: {p['sfondo']}; --sg-testo: {p['testo']}; --sg-bordo: {p['bordo']};
  --sg-attenuato: {p['attenuato']}; --sg-traccia: {p['traccia']};
  --sg-riquadro: {p['riquadro']}; --sg-frase: {p['frase_sfondo']};
  --sg-etichetta: {p['etichetta_sfondo']}; --sg-accento: {p['accento']};
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  color: var(--sg-testo); }}
.sg-sezione {{ background: var(--sg-sfondo); border: 1px solid var(--sg-bordo);
  border-radius: 12px; padding: 14px 16px; margin: 0 0 12px 0; }}
.sg-titolo {{ margin: 0 0 10px 0; font-size: 16px; color: var(--sg-testo); }}
.sg-riga-barra {{ display: flex; align-items: center; gap: 8px; margin: 6px 0; }}
.sg-esito {{ flex: 0 0 14px; font-weight: 700; text-align: center; }}
.sg-traccia {{ flex: 1 1 auto; height: 14px; background: var(--sg-traccia);
  border-radius: 999px; overflow: hidden; }}
.sg-riempimento {{ height: 100%; border-radius: 999px; }}
.sg-valore {{ flex: 0 0 52px; text-align: right; font-weight: 700; }}
.sg-modello {{ color: var(--sg-attenuato); font-size: 13px; margin: 8px 0 0 0; }}
.sg-etichette {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }}
.sg-etichetta {{ background: var(--sg-etichetta); border: 1px solid var(--sg-bordo);
  border-radius: 999px; padding: 4px 12px; font-size: 13px; }}
.sg-griglia {{ display: grid; gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }}
@media (max-width: 640px) {{ .sg-griglia {{ grid-template-columns: 1fr; }} }}
.sg-squadra {{ background: var(--sg-riquadro); border: 1px solid var(--sg-bordo);
  border-radius: 10px; padding: 12px 14px; }}
.sg-nome {{ margin: 0 0 6px 0; font-size: 16px; color: var(--sg-testo); }}
.sg-testa {{ display: flex; align-items: baseline; gap: 10px; margin-bottom: 8px; }}
.sg-pos {{ font-size: 34px; font-weight: 800; line-height: 1; }}
.sg-freccia {{ font-size: 14px; font-weight: 700; }}
.sg-riga-dati {{ margin: 0 0 8px 0; }}
.sg-distanze {{ margin: 0 0 10px 0; padding-left: 18px; }}
.sg-frase {{ background: var(--sg-frase); border-left: 4px solid var(--sg-accento);
  border-radius: 6px; padding: 8px 10px; }}
.sg-attenuato {{ color: var(--sg-attenuato); }}
</style>"""


# ---------------------------------------------------------------------------
# 1. Probabilita': barre 1/X/2, modello, pronostico e gol
# ---------------------------------------------------------------------------
def _html_probabilita(scheda: Dict[str, Any]) -> str:
    prob = (scheda or {}).get("probabilita") or {}
    quote = prob.get("quote") or {}
    righe: List[str] = ['<section class="sg sg-sezione">',
                        '<h3 class="sg-titolo">Probabilità</h3>']
    if not prob.get("disponibile") or not quote:
        righe.append(f'<p class="sg-attenuato">{_esc(FRASE_QUOTE_ASSENTI)}</p>')
        righe.append("</section>")
        return "\n".join(righe)

    for esito in ESITI:
        pct = _percentuale(quote.get(esito))
        larghezza = f"{pct:.1f}" if pct is not None else "0.0"
        righe.append(
            '<div class="sg-riga-barra">'
            f'<span class="sg-esito">{esito}</span>'
            f'<div class="sg-traccia"><div class="sg-riempimento" '
            f'style="width:{larghezza}%;background:{COLORI_ESITI[esito]}"></div></div>'
            f'<span class="sg-valore">{_fmt_percentuale(pct)}</span>'
            "</div>")

    # Le probabilita' del modello: riga piccola e grigia, SOLO se ci sono.
    modello = prob.get("modello") or {}
    if prob.get("modello_disponibile") and any(
            _numero(modello.get(e)) is not None for e in ESITI):
        pezzi = " ".join(f"{e} {_fmt_modello(modello.get(e))}" for e in ESITI)
        righe.append(f'<p class="sg-modello">Modello: {_esc(pezzi)}</p>')

    pronostico = str((scheda or {}).get("pronostico") or "").strip()
    if pronostico in ESITI:
        testo_pronostico = _esc(pronostico)
    else:
        testo_pronostico = f"— ({NOTA_SOTTO_SOGLIA})"
    totals = (scheda or {}).get("totals") or {}
    p_over = _percentuale(totals.get("p_over"))
    testo_gol = f"P(Over 2,5) {_fmt_percentuale(p_over)}"
    righe.append(
        '<div class="sg-etichette">'
        f'<span class="sg-etichetta"><strong>Pronostico:</strong> {testo_pronostico}</span>'
        f'<span class="sg-etichetta"><strong>Gol:</strong> {_esc(testo_gol)}</span>'
        "</div>")
    righe.append("</section>")
    return "\n".join(righe)


def html_probabilita(scheda: Dict[str, Any], tema: str = "chiaro") -> str:
    """La sezione Probabilita' della scheda, come stringa HTML.

    Tre barre orizzontali (1 blu, X grigia, 2 arancione) con la
    percentuale a destra; sotto, solo se disponibili, le probabilita' del
    modello in una riga grigia piccola; poi le due etichette arrotondate
    del pronostico e del gol (P(Over 2,5)).
    """
    return _stile(palette_di(tema)) + "\n" + _html_probabilita(scheda)


# ---------------------------------------------------------------------------
# 2. Classifica: un riquadro per squadra
# ---------------------------------------------------------------------------
def _freccia_html(pos: Optional[int], pos_prec: Optional[int]) -> str:
    """La freccia rispetto alla giornata precedente, con "(era N)".

    Migliorata (``pos`` piu' piccola): triangolo su, verde. Peggiorata:
    triangolo giu', rosso. Ferma: segno uguale, grigio. Senza giornata
    precedente: un trattino grigio con la nota, mai un ``None``.
    """
    if pos is None or pos_prec is None:
        return ('<span class="sg-freccia" style="color:'
                f'{COLORI_FRECCIA["ferma"]}">— (nessuna giornata precedente)</span>')
    if pos < pos_prec:
        simbolo, classe = "▲", COLORI_FRECCIA["su"]
    elif pos > pos_prec:
        simbolo, classe = "▼", COLORI_FRECCIA["giu"]
    else:
        simbolo, classe = "=", COLORI_FRECCIA["ferma"]
    return (f'<span class="sg-freccia" style="color:{classe}">'
            f"{simbolo} (era {pos_prec})</span>")


def _distanza_in_parole(distanza: Optional[int], riferimento: str) -> str:
    """Distanza in punti da una posizione: "a 5 punti dal sesto posto"."""
    if distanza is None:
        return "distanza non disponibile"
    if distanza > 0:
        return f"a {_punti(distanza)} dal {riferimento}"
    if distanza == 0:
        return f"appaiata al {riferimento}"
    return f"{_punti(-distanza)} sopra il {riferimento}"


def _riquadro_squadra(scheda: Dict[str, Any], ruolo: str) -> str:
    classifica = (scheda or {}).get("classifica") or {}
    dati = classifica.get(ruolo)
    nome = _esc(((scheda or {}).get(ruolo) or {}).get("nome")
                or (dati or {}).get("nome") or "?")
    if not dati:
        return ('<div class="sg-squadra">'
                f'<h4 class="sg-nome">{nome}</h4>'
                '<p class="sg-attenuato">Dati di classifica insufficienti '
                "per questa stagione.</p></div>")
    nome = _esc(dati.get("nome") or ((scheda or {}).get(ruolo) or {}).get("nome") or "?")
    pos = _intero(dati.get("pos"))
    pos_prec = _intero(dati.get("pos_prec"))
    righe = ['<div class="sg-squadra">',
             f'<h4 class="sg-nome">{nome}</h4>',
             '<div class="sg-testa">'
             f'<span class="sg-pos">{_fmt_intero(pos)}°</span>'
             f"{_freccia_html(pos, pos_prec)}</div>"]
    rimaste = dati.get("giornate_rimaste")
    if rimaste is None and classifica.get("n_squadre") is not None:
        giocate = _intero(dati.get("giocate"))
        rimaste = (max(0, 2 * (int(classifica["n_squadre"]) - 1) - giocate)
                   if giocate is not None else None)
    righe.append(
        '<p class="sg-riga-dati">'
        f"{_fmt_intero(dati.get('punti'))} punti · "
        f"{_fmt_intero(dati.get('giocate'))} partite giocate · "
        f"{_fmt_intero(rimaste)} giornate rimaste</p>")

    distanze: List[str] = []
    if pos != 1 and dati.get("dal_primo") is not None:
        distanze.append(_distanza_in_parole(_intero(dati.get("dal_primo")),
                                            "primo posto"))
    if dati.get("dal_quarto") is not None:
        distanze.append(_distanza_in_parole(_intero(dati.get("dal_quarto")),
                                            "quarto posto"))
    if dati.get("dal_sesto") is not None:
        distanze.append(_distanza_in_parole(_intero(dati.get("dal_sesto")),
                                            "sesto posto"))
    zona = _intero(dati.get("dalla_zona"))
    if zona is not None:
        if zona > 0:
            distanze.append(f"{_punti(zona)} sopra la zona retrocessione")
        elif zona == 0:
            distanze.append("appaiata alla zona retrocessione")
        else:
            distanze.append(f"{_punti(-zona)} dentro la zona retrocessione")
    if dati.get("spareggio"):
        distanze.append("terzultima = spareggio")
    if distanze:
        righe.append('<ul class="sg-distanze">'
                     + "".join(f"<li>{_esc(d)}</li>" for d in distanze)
                     + "</ul>")
    frase = dati.get("frase")
    if frase:
        righe.append(f'<div class="sg-frase">{_esc(frase)}</div>')
    righe.append("</div>")
    return "\n".join(righe)


def _html_classifica(scheda: Dict[str, Any]) -> str:
    return "\n".join([
        '<section class="sg sg-sezione">',
        '<h3 class="sg-titolo">Classifica</h3>',
        '<div class="sg-griglia">',
        _riquadro_squadra(scheda, "casa"),
        _riquadro_squadra(scheda, "trasferta"),
        "</div>",
        "</section>",
    ])


def html_classifica(scheda: Dict[str, Any], tema: str = "chiaro") -> str:
    """La sezione Classifica della scheda, come stringa HTML.

    Un riquadro per squadra (nome, posizione in grande con il simbolo di
    grado e la freccia rispetto a ``pos_prec``, punti, giocate, giornate
    rimaste, distanze e frase obiettivo in un riquadro colorato), in una
    griglia che sotto i 640 pixel mette i riquadri uno sotto l'altro.
    """
    return _stile(palette_di(tema)) + "\n" + _html_classifica(scheda)


def html_scheda(scheda: Dict[str, Any], tema: str = "chiaro") -> str:
    """Le due sezioni grafiche della scheda (probabilita' e classifica)."""
    return "\n".join([
        _stile(palette_di(tema)),
        '<div class="sg">',
        _html_probabilita(scheda),
        _html_classifica(scheda),
        "</div>",
    ])
