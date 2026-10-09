"""REGOLA: ogni modifica che cambia le probabilita' (o la selezione) del Top Mix alza
``prediction_registry.SELECTOR_VERSION_CURRENT``.

Il test calcola un'impronta AST delle funzioni che producono le probabilita' e la
selezione visibili (Poisson, Elo, blend 1X2, selezione, riga) e delle due costanti
che le pesano. Commenti e docstring non entrano nell'impronta; il codice si'.

Se l'impronta cambia, il test fallisce: bisogna (1) alzare SELECTOR_VERSION_CURRENT e
(2) aggiungere la nuova impronta a ``IMPRONTE`` sotto la nuova versione. La tabella
e' append-only: le impronte vecchie restano, cosi' la storia delle versioni e' leggibile.

Non copre ``calcola_righe_top_mix``: contiene anche la logica dell'ombra, che non
cambia le probabilita' visibili. Le sue modifiche si rivedono a mano (vedi la regola
nel commento di ``SELECTOR_VERSION_PRE_1X2``).
"""
from __future__ import annotations

import ast
import hashlib
import logging
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

logging.getLogger("streamlit").setLevel(logging.ERROR)

import prediction_registry as R  # noqa: E402

APP = os.path.join(HERE, "app.py")
ELO = os.path.join(HERE, "models", "elo_engine.py")
MERCATO = os.path.join(HERE, "market_odds.py")

#: Funzioni (file, nome) e costanti (file, nome) che determinano probabilita' e selezione.
#: Dalla PR delle quote live il Top Mix VISIBILE sceglie sul mercato: entrano
#: nell'impronta anche il selettore di mercato, la costruzione della sua riga e
#: il de-vig (``market_odds``), perche' sono loro a produrre la probabilita' che
#: decide. Le funzioni del modello restano: la probabilita' del Drago e il
#: segnale "d'accordo" fanno parte della riga visibile.
FUNZIONI = (
    (APP, "get_full_poisson_two_heads"),
    (APP, "blend_elo_into_1x2"),
    (APP, "seleziona_riga_top_mix"),
    (APP, "seleziona_riga_top_mix_mercato"),
    (APP, "_riga_top_mix"),
    (APP, "_riga_top_mix_mercato"),
    (ELO, "predict_elo_probs"),
    (MERCATO, "devig_proporzionale"),
    (MERCATO, "ternaria_h2h"),
    (MERCATO, "probabilita_mercato"),
)
COSTANTI = (
    (APP, "POISSON_1X2_WEIGHT"),
    (APP, "TOP_MIX_ROUND_WINDOW_DAYS"),
    (MERCATO, "SOGLIA_TOPMIX_MERCATO"),
    (MERCATO, "SOGLIA_ACCORDO"),
    (MERCATO, "BOOKMAKER_PRIMARIO"),
    (MERCATO, "ESITI"),
)

#: Impronta di ciascuna versione del selettore (append-only).
#: ``topmix_1x2_gate025_ens06_v2`` e' l'impronta calcolata sull'insieme di
#: funzioni/costanti DI ALLORA (senza mercato): resta in tabella come storia, ma
#: non e' ricalcolabile col codice di oggi (l'insieme e' cambiato).
IMPRONTE = {
    "topmix_1x2_gate025_ens06_v2": "f2a287f0f70bba9eab5c1811ac661fb98a19f6796f9ead6e23d5af9e03e10222",
    # v3: il Top Mix VISIBILE sceglie sul mercato (de-vig proporzionale, soglia
    # 0,55) e l'impronta copre anche ``market_odds``. Le probabilita' del modello
    # non sono cambiate: sono cambiati il selettore visibile e la sua riga.
    "topmix_mercato_v3": "1d2787b0f45b0f91a6ba651809b6e9ecdb2ba7dec35972dafdb40814186a4bb5",
}


def _senza_docstring(nodo: ast.FunctionDef) -> ast.FunctionDef:
    corpo = nodo.body
    if corpo and isinstance(corpo[0], ast.Expr) and isinstance(getattr(corpo[0], "value", None), ast.Constant) \
            and isinstance(corpo[0].value.value, str):
        nodo.body = corpo[1:] or [ast.Pass()]
    return nodo


def impronta_da_sorgenti(sorgenti: dict, funzioni=FUNZIONI, costanti=COSTANTI) -> str:
    """Impronta sha256 dal testo dei file (``{percorso: testo}``); ignora commenti e docstring."""
    parti = []
    alberi = {}
    for percorso, testo in sorgenti.items():
        alberi[percorso] = ast.parse(testo)
    for percorso, nome in funzioni:
        fn = next(n for n in alberi[percorso].body if isinstance(n, ast.FunctionDef) and n.name == nome)
        parti.append(ast.dump(_senza_docstring(fn), annotate_fields=True, include_attributes=False))
    for percorso, nome in costanti:
        # ``Assign`` (``X = 1``) e ``AnnAssign`` (``X: int = 1``): entrambe
        # definiscono la costante, entrambe entrano nell'impronta.
        asg = next(n for n in alberi[percorso].body
                   if isinstance(n, (ast.Assign, ast.AnnAssign))
                   and any(getattr(t, "id", None) == nome
                           for t in (n.targets if isinstance(n, ast.Assign) else [n.target])))
        parti.append(ast.dump(asg.value, annotate_fields=True, include_attributes=False))
    return hashlib.sha256("\n".join(parti).encode("utf-8")).hexdigest()


def impronta_attuale() -> str:
    sorgenti = {}
    for percorso in {p for p, _ in FUNZIONI + COSTANTI}:
        with open(percorso, encoding="utf-8") as f:
            sorgenti[percorso] = f.read()
    return impronta_da_sorgenti(sorgenti)


#: Impronte storiche NON ricalcolabili col codice di oggi (l'insieme di
#: funzioni/costanti dell'impronta e' cambiato con la versione). Il test le
#: accetta senza confronto; la versione IN PROVA deve invece coincidere.
IMPRONTE_STORICHE_NON_RICALCOLABILI = frozenset({"topmix_1x2_gate025_ens06_v2"})


class TestRegolaVersioneSelettore(unittest.TestCase):

    def test_la_versione_in_prova_ha_la_sua_impronta(self):
        self.assertIn(R.SELECTOR_VERSION_CURRENT, IMPRONTE,
                      "versione in prova senza impronta: aggiungila a IMPRONTE")
        self.assertEqual(IMPRONTE[R.SELECTOR_VERSION_CURRENT], impronta_attuale(),
                         "Le probabilita' o la selezione del Top Mix sono cambiate: alza "
                         "SELECTOR_VERSION_CURRENT in prediction_registry.py e aggiungi la nuova "
                         "impronta a IMPRONTE sotto la nuova versione (le vecchie restano).")

    def test_il_codice_visibile_e_quello_di_cui_si_calcola_l_impronta(self):
        for percorso, nome in FUNZIONI:
            with open(percorso, encoding="utf-8") as f:
                self.assertIn(f"def {nome}(", f.read(), f"{nome} non trovata in {percorso}")

    def _sorgenti_base(self):
        return {percorso: open(percorso, encoding="utf-8").read()
                for percorso in {p for p, _ in FUNZIONI + COSTANTI}}

    def test_una_modifica_di_codice_cambia_l_impronta(self):
        base = self._sorgenti_base()
        cambiato = base[APP].replace("POISSON_1X2_WEIGHT = 0.25", "POISSON_1X2_WEIGHT = 0.30", 1)
        self.assertNotEqual(base[APP], cambiato, "fixture non valida: la costante non e' quella attesa")
        self.assertNotEqual(impronta_da_sorgenti(base),
                            impronta_da_sorgenti({**base, APP: cambiato}))

    def test_la_soglia_del_mercato_cambia_l_impronta(self):
        """La soglia del selettore di mercato fa parte dell'impronta."""
        base = self._sorgenti_base()
        cambiato = base[MERCATO].replace("SOGLIA_TOPMIX_MERCATO = 0.55",
                                         "SOGLIA_TOPMIX_MERCATO = 0.60", 1)
        self.assertNotEqual(base[MERCATO], cambiato,
                            "fixture non valida: la costante non e' quella attesa")
        self.assertNotEqual(impronta_da_sorgenti(base),
                            impronta_da_sorgenti({**base, MERCATO: cambiato}))

    def test_la_soglia_di_accordo_cambia_l_impronta(self):
        base = self._sorgenti_base()
        cambiato = base[MERCATO].replace("SOGLIA_ACCORDO = 0.55", "SOGLIA_ACCORDO = 0.60", 1)
        self.assertNotEqual(base[MERCATO], cambiato)
        self.assertNotEqual(impronta_da_sorgenti(base),
                            impronta_da_sorgenti({**base, MERCATO: cambiato}))

    def test_il_bookmaker_primario_cambia_l_impronta(self):
        base = self._sorgenti_base()
        cambiato = base[MERCATO].replace('BOOKMAKER_PRIMARIO = "pinnacle"',
                                         'BOOKMAKER_PRIMARIO = "betfair_ex_eu"', 1)
        self.assertNotEqual(base[MERCATO], cambiato)
        self.assertNotEqual(impronta_da_sorgenti(base),
                            impronta_da_sorgenti({**base, MERCATO: cambiato}))

    def test_commento_e_docstring_non_cambiano_l_impronta(self):
        base = self._sorgenti_base()
        con_commento = base[APP].replace("def blend_elo_into_1x2(",
                                         "# commento di prova sul blend\ndef blend_elo_into_1x2(", 1)
        self.assertNotEqual(base[APP], con_commento)
        self.assertEqual(impronta_da_sorgenti(base),
                         impronta_da_sorgenti({**base, APP: con_commento}))

    def test_la_regola_e_scritta_accanto_alla_versione(self):
        with open(os.path.join(HERE, "prediction_registry.py"), encoding="utf-8") as f:
            testo = f.read()
        blocco = testo[testo.index("SELECTOR_VERSION_PRE_1X2 ="):testo.index("SELECTOR_VERSION_PRE_1X2 =") + 1500]
        self.assertIn("alza", blocco.lower())


if __name__ == "__main__":
    unittest.main()
