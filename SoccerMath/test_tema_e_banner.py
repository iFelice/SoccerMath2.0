"""Il tema dell'app (`.streamlit/config.toml`) e il banner in cima alla pagina.

Due cose che nessun test guardava e che si rompono in silenzio: una chiave di
colore scritta male (Streamlit la ignora e resta il default) e un banner che
si riprende `aspect-ratio` o `max-height` e torna alto 600px dentro Safari.

Cosa si verifica
----------------
* **config.toml, tema chiaro**: le dodici chiavi della commessa, ognuna col suo
  esadecimale con il cancelletto, `base = "light"`, il font invariato e la
  `baseRadius` a 10px;
* **config.toml, tema scuro**: le undici chiavi della variante scura, con i
  valori della commessa; font e `base` restano nel blocco chiaro (la variante
  scura eredita, non li riscrive);
* **nessuna chiave inventata**: l'insieme delle chiavi e' ESATTAMENTE quello
  atteso, cosi' un refuso (`borderColour`, `dataframeBorder`) non passa
  inosservato — Streamlit ignora le opzioni che non conosce;
* **banner**: `height: 180px`, `background-size: contain`,
  `background-position: center`, e NIENTE `aspect-ratio` ne' `max-height`
  (il riquadro non deve piu' crescere fino a 600px).

Il file di configurazione si legge con `tomllib` (Python 3.11); il banner si
legge dal blocco `<style>` di `app.py` con un piccolo estrattore di regole CSS
(`blocco_css`, funzione pura).

Esecuzione:
    python -m pytest SoccerMath/test_tema_e_banner.py -v
"""
from __future__ import annotations

import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.dirname(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

CONFIG = os.path.join(HERE, ".streamlit", "config.toml")
APP = os.path.join(HERE, "app.py")

#: Il tema chiaro: chiave -> valore atteso (esadecimali con il cancelletto).
CHIARO = {
    "primaryColor": "#1d4ed8",
    "backgroundColor": "#f0f2f5",
    "secondaryBackgroundColor": "#ffffff",
    "textColor": "#1a1d23",
    "borderColor": "#dde1e8",
    "dataframeBorderColor": "#dde1e8",
    "dataframeHeaderBackgroundColor": "#f6f7f9",
    "dataframeHeaderTextColor": "#5b6270",
    "blueColor": "#2563eb",
    "orangeColor": "#c96512",
    "grayColor": "#7b8494",
    "baseRadius": "10px",
}

#: La variante scura: le chiavi che cambiano nel buio.
SCURO = {
    "primaryColor": "#4d8fdb",
    "backgroundColor": "#0e1117",
    "secondaryBackgroundColor": "#171a22",
    "textColor": "#f2f3f5",
    "borderColor": "#2a2f3a",
    "dataframeBorderColor": "#2a2f3a",
    "dataframeHeaderBackgroundColor": "#1d212b",
    "dataframeHeaderTextColor": "#a7adba",
    "blueColor": "#4d8fdb",
    "orangeColor": "#e8913a",
    "grayColor": "#8a93a6",
}

#: Le sole chiavi ammesse in `[theme]` (base, font, i colori, i raggi).
CHIAVI_CHIARO = set(CHIARO) | {"base", "font"}

#: Le sole chiavi ammesse in `[theme.dark]`: sono quelle elencate nella
#: commessa (font e base si ereditano dal blocco chiaro).
CHIAVI_SCURO = set(SCURO)

#: Un esadecimale CSS: cancelletto + sei cifre, minuscole.
ESADECIMALE = re.compile(r"^#[0-9a-f]{6}$")


def leggi_config(percorso: str = CONFIG) -> dict:
    """Il `config.toml` come dizionario (``tomllib``, nessuna dipendenza in piu')."""
    import tomllib
    with open(percorso, "rb") as fh:
        return tomllib.load(fh)


def css_app(percorso: str = APP) -> str:
    """Tutto il testo di `app.py` (il CSS vive dentro una stringa markdown)."""
    with open(percorso, encoding="utf-8") as fh:
        return fh.read()


def blocco_css(testo: str, selettore: str) -> dict:
    """Le dichiarazioni della regola ``selettore`` in un testo CSS.

    Funzione PURA: cerca il selettore, prende quello che sta fra la sua graffa
    e la prima graffa di chiusura e lo spezza in ``{proprieta': valore}``.
    Solleva con l'elenco dei selettori trovati se non c'e': un selettore
    rinominato deve far fallire il test, non farlo passare a vuoto.
    """
    for trovato in re.finditer(re.escape(selettore) + r"\s*\{([^{}]*)\}", testo):
        dichiarazioni = {}
        for pezzo in trovato.group(1).split(";"):
            if ":" not in pezzo:
                continue
            proprieta, valore = pezzo.split(":", 1)
            dichiarazioni[" ".join(proprieta.split())] = " ".join(valore.split())
        return dichiarazioni
    trovati = sorted({s.split("{")[0].strip() for s in testo.split("}") if "{" in s})
    raise AssertionError(f"regola {selettore!r} non trovata; selettori nel testo: "
                         f"{[t for t in trovati if 'safari' in t or 'banner' in t]}")


class TestBanner(unittest.TestCase):
    """Il banner in cima alla pagina: 180px, immagine intera e centrata."""

    def setUp(self):
        self.css = css_app()
        self.regola = blocco_css(self.css, ".safari-safe-banner")

    def test_altezza_fissa_180(self):
        self.assertEqual("180px", self.regola["height"])
        self.assertEqual("100%", self.regola["width"])

    def test_niente_aspect_ratio_ne_max_height(self):
        self.assertNotIn("aspect-ratio", self.regola,
                         "l'aspect-ratio faceva crescere il riquadro fino a 600px")
        self.assertNotIn("max-height", self.regola)
        self.assertNotIn("1056 / 2496", self.css,
                         "la vecchia proporzione dell'immagine non deve restare")
        self.assertNotIn("max-height: 600px", self.css)

    def test_immagine_intera_e_centrata(self):
        self.assertEqual("contain", self.regola["background-size"],
                         "«contain»: l'immagine ci sta tutta, niente tagli")
        self.assertEqual("no-repeat", self.regola["background-repeat"])
        self.assertEqual("center center", self.regola["background-position"])
        self.assertIn("Banner%20soccermath2.0.png", self.regola["background-image"])

    def test_il_banner_e_ancora_disegnato_in_pagina(self):
        self.assertIn('<div class="safari-safe-banner"></div>', self.css,
                      "la regola senza il div non mostrerebbe niente")


class TestTemaChiaro(unittest.TestCase):
    """`[theme]`: i colori della commessa, con il cancelletto."""

    def setUp(self):
        self.tema = leggi_config()["theme"]

    def test_i_colori_sono_quelli_della_commessa(self):
        for chiave, atteso in CHIARO.items():
            with self.subTest(chiave=chiave):
                self.assertEqual(atteso, self.tema.get(chiave))

    def test_ogni_colore_e_un_esadecimale_con_il_cancelletto(self):
        for chiave in CHIARO:
            if chiave == "baseRadius":
                continue
            with self.subTest(chiave=chiave):
                valore = self.tema[chiave]
                self.assertRegex(valore, ESADECIMALE,
                                 f"{chiave}: serve un esadecimale con il cancelletto")
                self.assertEqual(valore.lower(), valore,
                                 f"{chiave}: esadecimale in minuscolo")

    def test_font_e_base_invariati(self):
        self.assertEqual("light", self.tema["base"])
        self.assertEqual("sans serif", self.tema["font"])

    def test_la_base_radius_e_10px(self):
        self.assertEqual("10px", str(self.tema["baseRadius"]))

    def test_nessuna_chiave_inventata(self):
        """Un refuso in una chiave non da' errore: Streamlit la ignora."""
        # ``dark`` e' la sotto-tabella della variante scura: non e' una chiave
        # di colore del tema chiaro.
        chiavi = set(self.tema) - {"dark"}
        self.assertEqual(CHIAVI_CHIARO, chiavi,
                         f"chiavi in piu': {sorted(chiavi - CHIAVI_CHIARO)}, "
                         f"mancanti: {sorted(CHIAVI_CHIARO - chiavi)}")


class TestTemaScuro(unittest.TestCase):
    """`[theme.dark]`: le chiavi che cambiano nel buio, e quelle che si ereditano."""

    def setUp(self):
        self.config = leggi_config()
        self.scuro = self.config["theme"]["dark"]

    def test_i_colori_sono_quelli_della_commessa(self):
        for chiave, atteso in SCURO.items():
            with self.subTest(chiave=chiave):
                self.assertEqual(atteso, self.scuro.get(chiave))

    def test_ogni_colore_e_un_esadecimale_con_il_cancelletto(self):
        for chiave in SCURO:
            with self.subTest(chiave=chiave):
                self.assertRegex(self.scuro[chiave], ESADECIMALE)

    def test_nessuna_chiave_inventata(self):
        self.assertEqual(CHIAVI_SCURO, set(self.scuro),
                         f"chiavi in piu': {sorted(set(self.scuro) - CHIAVI_SCURO)}, "
                         f"mancanti: {sorted(CHIAVI_SCURO - set(self.scuro))}")

    def test_il_tema_scuro_eredita_font_e_base(self):
        """`font` e `base` stanno solo nel blocco chiaro: qui sarebbero un doppione."""
        for chiave in ("font", "base"):
            with self.subTest(chiave=chiave):
                self.assertNotIn(chiave, self.scuro)
                self.assertIn(chiave, self.config["theme"])

    def test_i_due_temi_cambiano_ogni_colore(self):
        """Ogni chiave della variante scura ha un valore SUO, diverso dal chiaro.

        Se un colore restasse identico nei due blocchi vorrebbe dire che la
        variante scura non e' stata scritta davvero (o che e' un refuso).
        """
        chiaro = self.config["theme"]
        for chiave in SCURO:
            with self.subTest(chiave=chiave):
                self.assertNotEqual(chiaro[chiave], self.scuro[chiave],
                                    f"{chiave} non cambia fra chiaro e scuro")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
