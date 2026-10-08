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

#: Funzioni (file, nome) e costanti (file, nome) che determinano probabilita' e selezione.
FUNZIONI = (
    (APP, "get_full_poisson_two_heads"),
    (APP, "blend_elo_into_1x2"),
    (APP, "seleziona_riga_top_mix"),
    (APP, "_riga_top_mix"),
    (ELO, "predict_elo_probs"),
)
COSTANTI = (
    (APP, "POISSON_1X2_WEIGHT"),
    (APP, "TOP_MIX_ROUND_WINDOW_DAYS"),
)

#: Impronta di ciascuna versione del selettore (append-only).
IMPRONTE = {
    "topmix_1x2_gate025_ens06_v2": "f2a287f0f70bba9eab5c1811ac661fb98a19f6796f9ead6e23d5af9e03e10222",
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
        asg = next(n for n in alberi[percorso].body
                   if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == nome for t in n.targets))
        parti.append(ast.dump(asg.value, annotate_fields=True, include_attributes=False))
    return hashlib.sha256("\n".join(parti).encode("utf-8")).hexdigest()


def impronta_attuale() -> str:
    sorgenti = {}
    for percorso in {p for p, _ in FUNZIONI + COSTANTI}:
        with open(percorso, encoding="utf-8") as f:
            sorgenti[percorso] = f.read()
    return impronta_da_sorgenti(sorgenti)


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

    def test_una_modifica_di_codice_cambia_l_impronta(self):
        with open(APP, encoding="utf-8") as f:
            testo = f.read()
        base = {APP: testo, ELO: open(ELO, encoding="utf-8").read()}
        cambiato = testo.replace("POISSON_1X2_WEIGHT = 0.25", "POISSON_1X2_WEIGHT = 0.30", 1)
        self.assertNotEqual(testo, cambiato, "fixture non valida: la costante non e' quella attesa")
        self.assertNotEqual(impronta_da_sorgenti(base),
                            impronta_da_sorgenti({**base, APP: cambiato}))

    def test_commento_e_docstring_non_cambiano_l_impronta(self):
        with open(APP, encoding="utf-8") as f:
            testo = f.read()
        base = {APP: testo, ELO: open(ELO, encoding="utf-8").read()}
        con_commento = testo.replace("def blend_elo_into_1x2(",
                                     "# commento di prova sul blend\ndef blend_elo_into_1x2(", 1)
        self.assertNotEqual(testo, con_commento)
        self.assertEqual(impronta_da_sorgenti(base),
                         impronta_da_sorgenti({**base, APP: con_commento}))

    def test_la_regola_e_scritta_accanto_alla_versione(self):
        with open(os.path.join(HERE, "prediction_registry.py"), encoding="utf-8") as f:
            testo = f.read()
        blocco = testo[testo.index("SELECTOR_VERSION_PRE_1X2 ="):testo.index("SELECTOR_VERSION_PRE_1X2 =") + 1500]
        self.assertIn("alza", blocco.lower())


if __name__ == "__main__":
    unittest.main()
