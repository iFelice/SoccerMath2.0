"""Genera il fixture "PRIMA del refactor" del selettore Top Mix.

Il refactor di ``audit/margini_migliorabili_topmix.md`` §9 punto 2 sposta la
selezione di riga fuori da ``fetch_and_calc_top_mix`` nella funzione pura
``seleziona_riga_top_mix``. Per dimostrare che e' un refactor NEUTRO serve il
sorgente PRE-refactor, verbatim: questo script lo pesca da git e lo scrive in
``SoccerMath/test_fixtures/topmix_selettore_pre_refactor.py`` come testo, senza
riscrivere niente (la trascrizione a mano e' esattamente il rischio che il
refactor voleva eliminare).

Uso::

    python audit/make_topmix_selector_fixture.py              # scrive il fixture
    python audit/make_topmix_selector_fixture.py --check      # rigenera e confronta

Il fixture contiene:

* ``TESTO_FUNZIONE``: la funzione ``fetch_and_calc_top_mix`` di ``ORIGINE``,
  senza la riga di decoratore ``@st.cache_data(...)`` (nel test non serve: la
  funzione viene eseguita da un namespace con gli stub iniettati). Il nome e'
  lasciato identico perche' il test la recupera dal namespace per nome;
* ``RIGHE_CHIAVE``: le righe non-commento del blocco di selezione, dedentate.
  ``test_topmix_selector_parity.py`` le verifica tutte presenti sia nel
  fixture sia nel nuovo ``seleziona_riga_top_mix`` -> e' il guard contro le
  riscritture: un numero cambiato sarebbe visibile in entrambe le liste.
"""
from __future__ import annotations

import argparse
import ast
import os
import subprocess
import sys

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

APP_BLOB = "SoccerMath/app.py"
ORIGINE = "16d4e73"        # ultimo commit con il corpo di selezione INLINE
FUNZIONE = "fetch_and_calc_top_mix"
OUT = os.path.join(_REPO_ROOT, "SoccerMath", "test_fixtures",
                   "topmix_selettore_pre_refactor.py")

TEMPLATE = '''"""Selettore Top Mix PRIMA del refactor: testo verbatim, non un riassunto.

Generato da ``audit/make_topmix_selector_fixture.py`` (``--check`` rigenera e
confronta) a partire da ``{origine}:{blob}``. Usato da
``SoccerMath/test_topmix_selector_parity.py``, che esegue ``TESTO_FUNZIONE`` in un
namespace con gli stessi stub del percorso nuovo e confronta le righe prodotte:
stesso identico output = refactor neutro.

NON e' codice di produzione e non deve essere importato da ``app.py``. Se ti
serve cambiarlo, rigenera il fixture: modificarlo a mano distruggerebbe l'unica
prova che il confronto e' con il codice di prima.
"""
from __future__ import annotations

ORIGINE = {origine_r}
BLOB = {blob_r}
NOME = {nome_r}

# Corpo della funzione PRIMA del refactor (riga decoratore rimossa; il resto e'
# byte-identico al blob, vedi test_topmix_selector_parity.py::test_provenienza).
TESTO_FUNZIONE = {testo_r}

# Righe non-commento del blocco di selezione, dedentate: devono comparire sia
# qui sia nella nuova funzione pura. E' il guard contro le riscritture.
# Chiavi del dizionario che il selettore produceva (ordine originale).
CHIAVI_RIGA = {chiavi_riga_r}
RIGHE_CHIAVE = {righe_r}
'''


def blob_text(ref: str, path: str = APP_BLOB) -> str:
    r = subprocess.run(["git", "-C", _REPO_ROOT, "show", f"{ref}:{path}"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"git show {ref}:{path} fallito: {r.stderr.strip()[:200]}")
    return r.stdout


def _riga_decoratore(src: str, nome: str) -> str:
    """La riga di decoratore immediatamente sopra ``def nome(``, se c'e'."""
    righe = src.splitlines(keepends=True)
    for i, riga in enumerate(righe):
        if riga.startswith(f"def {nome}(") and i and righe[i - 1].lstrip().startswith("@"):
            return righe[i - 1]
    return ""


def funzione_testo(src: str, nome: str) -> str:
    """Sorgente della funzione al top-level, decoratori esclusi."""
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == nome:
            righe = src.splitlines(keepends=True)
            return "".join(righe[node.lineno - 1: node.end_lineno])
    raise SystemExit(f"funzione {nome} non trovata in {APP_BLOB}")


def righe_chiave(testo_fn: str) -> list:
    """La SOLA matematica di selezione, dai mercati al gate, dedentate.

    Si ferma alla riga del gate: cio' che viene dopo (assemblaggio della riga
    con i campi del match) nel nuovo codice cambia per costruzione, mentre la
    matematica di selezione non deve cambiare di un carattere.
    """
    fuori = []
    attivo = False
    for riga in testo_fn.splitlines():
        st = riga.strip()
        if not attivo:
            attivo = st.startswith("mercati = {")
            if not attivo:
                continue
        if st.startswith("all_preds.append("):
            break
        if not st or st.startswith("#"):
            continue
        fuori.append(st)
    return fuori


def chiavi_riga(testo_fn: str) -> list:
    """Le chiavi del dizionario della riga, nell'ordine in cui erano scritte."""
    blocco = testo_fn[testo_fn.index("all_preds.append({"):]
    fine = blocco.index("})")
    return [m for m in __import__("re").findall(r'"([a-zA-Z_]+)":', blocco[:fine])]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default=ORIGINE)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    src = blob_text(a.ref)
    testo = funzione_testo(src, FUNZIONE)
    deco = _riga_decoratore(src, FUNZIONE)
    if testo.startswith(deco):          # ast: lineno punta gia' alla def
        testo = testo[len(deco):]
    assert not deco or deco not in testo, "decoratore ancora nel testo"
    assert testo.startswith(f"def {FUNZIONE}("), testo[:60]
    chiavi = righe_chiave(testo)
    chiavi_riga_lista = chiavi_riga(testo)
    assert any(r.startswith("min_conf = 0.55") for r in chiavi), chiavi
    assert any(r.startswith("min_conf = 0.60") for r in chiavi), chiavi
    assert any("abs(poisson_prob - elo_prob) < 0.25" in r for r in chiavi), chiavi
    assert any("ELO_ENSEMBLE_W * poisson_prob" in r for r in chiavi), chiavi
    assert any(r.startswith("best_mkt = max(mercati") for r in chiavi), chiavi
    assert any(r.startswith("if confidence >= min_conf") for r in chiavi), chiavi
    for attesa in ("market", "mercato_standard", "prob", "prob_val", "poisson",
                   "elo", "elo_disponibile"):
        assert attesa in chiavi_riga_lista, (attesa, chiavi_riga_lista)

    nuovo = TEMPLATE.format(origine=a.ref, blob=APP_BLOB, origine_r=repr(a.ref),
                             blob_r=repr(APP_BLOB), nome_r=repr(FUNZIONE),
                             testo_r=repr(testo), righe_r=repr(chiavi),
                             chiavi_riga_r=repr(chiavi_riga_lista))
    ast.parse(nuovo)

    if a.check:
        attuale = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        if attuale != nuovo:
            print("::error::fixture non allineato al blob: rigenerare senza --check")
            return 1
        print(f"fixture coerente con {a.ref}:{APP_BLOB} ({len(chiavi)} righe chiave)")
        return 0

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(nuovo)
    print(f"scritto: {OUT}  ({len(chiavi)} righe di selezione, "
          f"{len(chiavi_riga_lista)} chiavi di riga, {len(testo)} char)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
