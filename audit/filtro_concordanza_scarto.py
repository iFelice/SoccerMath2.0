#!/usr/bin/env python3
"""filtro_concordanza_scarto.py — verifica del "filtro di concordanza" sulle scelte
di mercato del replay ``topmix_mercato_v3`` (campione della PR #49).

IPOTESI (punto 1 della commessa). Campione: le 1.302 scelte di mercato del replay
``topmix_mercato_v3`` (PR #49), ciascuna con probabilita' di mercato ``p_m``
dell'esito scelto e probabilita' del modello Drago ``p_d`` per lo stesso esito,
walk-forward come in produzione. Scarto = p_d − p_m.

Filtro proposto: una scelta passa se ``p_m >= 0,75`` oppure ``|scarto| <= 0,05``.
Soglie FISSE: nessuna ricerca di soglie alternative.

La REGOLA DICHIARATA e' la costante ``RULE_TEXT``: finisce in testa al referto
prima dei numeri e non viene modificata dopo averli visti. Il referto generato e'
``audit/results/filtro_concordanza_scarto.md``.

Come
----
* il campione si ricostruisce con le funzioni di PRODUZIONE gia' usate dal replay
  ``audit/replay_topmix_mercato.py`` (frame PR #49, campionatura 2024/25 + 2025/26,
  selettore ``app.seleziona_riga_top_mix_mercato``): nessuna formula riscritta;
* ``p_m`` = probabilita' di mercato dell'esito scelto, ``p_d`` = probabilita' del
  modello sullo STESSO esito (colonne del replay);
* incertezza: bootstrap a blocchi lega x stagione x data, 2000 repliche con
  reimmissione, IC 95% percentile, seme fisso;
* regressione logistica dell'esito su logit(p_m) e scarto (IRLS), IC dei
  coefficienti dallo stesso bootstrap a blocchi.

Nessuna rete, nessuna scrittura nel Registro, nessuna chiamata a The Odds API,
nessuna modifica a ``SoccerMath/``.

Output
  * ``audit/results/filtro_concordanza_scarto.md``  referto (committato);
  * ``audit/output/filtro_concordanza_scarto.json`` payload (non versionato).

Uso: ``python audit/filtro_concordanza_scarto.py [--reps 2000] [--seed 20261010]``
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import OrderedDict
from datetime import datetime, timezone

import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

OUT_DIR = os.path.join(_AUDIT_DIR, "output")
REPORT_PATH = os.path.join(_AUDIT_DIR, "results", "filtro_concordanza_scarto.md")
JSON_PATH = os.path.join(OUT_DIR, "filtro_concordanza_scarto.json")

# Soglie FISSE del filtro proposto (nessuna ricerca di soglie alternative).
SOGLIA_ALTA = 0.75          # p_m >= 0,75 -> la scelta passa
TOLLERANZA_SCARTO = 0.05    # |scarto| <= 0,05 -> la scelta passa
FASCE_PM = ((0.55, 0.60), (0.60, 0.65), (0.65, 0.75))

DEFAULT_REPS = 2000
DEFAULT_SEED = 20261010

# Limiti dichiarati del referto (fissati prima dei numeri, come la regola).
LIMITI = [
    "Le stagioni 2024/25 e 2025/26 sono già state usate dal progetto: "
    "l'ipotesi del filtro è nuova, ma i dati non sono vergini. L'ipotesi è "
    "stata formulata dopo aver visto più volte queste stagioni.",
    "Le probabilità di mercato vengono dai CSV storici B365 pre-chiusura "
    "de-vigati proporzionalmente (fonte del replay della PR #49), non dalle "
    "quote live di produzione.",
    "Lo scarto p_d − p_m è calcolato sullo stesso esito scelto dal mercato: "
    "non è uno scarto medio sulle tre vie.",
    "I bootstrap a blocchi lega × stagione × data tengono conto della "
    "correlazione entro la stessa giornata di lega; non delle altre "
    "dipendenze (formazioni, mercati comuni).",
    "La regressione logistica è associativa: il coefficiente dello scarto "
    "non identifica un effetto causale del modello.",
    "Colonna \"d'accordo\": definizione di produzione (stesso esito, entrambi "
    "≥ 0,55). Nessuna soglia alternativa è stata cercata.",
    "Nessuna modifica a SoccerMath/ né a app.py; nessun --write; nessuna "
    "chiamata a The Odds API.",
]

# ---------------------------------------------------------------------------\
# REGOLA DICHIARATA — scritta qui PRIMA dei numeri, non modificata dopo.
# ---------------------------------------------------------------------------
RULE_TEXT = """\
# Filtro di concordanza sulle scelte di mercato (`topmix_mercato_v3`)

## Regola dichiarata (prima dei numeri; questa sezione non viene modificata dopo)

**Campione.** Le 1.302 scelte di mercato del replay `topmix_mercato_v3` (PR #49),
ciascuna con probabilità di mercato `p_m` dell'esito scelto e probabilità del
modello Drago `p_d` per lo stesso esito, walk-forward come in produzione
(blend 0,25 Poisson + 0,75 Elo, colonne `m0/m1/m2` del frame della PR #49).
Scarto = `p_d − p_m`. Il replay deve stare in parità con la PR #49
(1302 / 1144 / 335, Δn = 0) prima di ogni numero di questo referto.

**Filtro proposto.** Una scelta passa se `p_m ≥ 0,75` **oppure** `|scarto| ≤ 0,05`.
Soglie fisse: nessuna ricerca di soglie alternative, in nessuna direzione.

**Gruppi.**
- "passa" ed "esclusa" sono calcolati sulle sole scelte con `p_m < 0,75`
  (così il confronto è a parità di probabilità di mercato e il criterio
  sotto test è quello di concordanza): "passa" = `|scarto| ≤ 0,05`,
  "esclusa" = `|scarto| > 0,05`.
- Le escluse si dividono in "modello più alto" (scarto > +0,05) e
  "modello più basso" (scarto < −0,05).
- Il filtro intero in produzione manterrebbe anche le scelte con `p_m ≥ 0,75`
  (passano per definizione): l'esito della regola è riportato anche con
  "passa" esteso a tutte le scelte mantenute dal filtro, come sola sensibilità.
  Il verdetto segue la definizione principale (solo `p_m < 0,75`).

**Incertezza.** Bootstrap a blocchi lega × stagione × data, 2.000 repliche con
reimmissione, IC 95% percentile, seme fisso. `f − p_m` = frequenza di vincita
del gruppo meno la `p_m` media dello stesso gruppo (con segno). La differenza
fra due gruppi è appaiata: gli stessi draw di blocchi valutano entrambi.

**Filtro di concordanza — regola di decisione.** Il filtro si propone per la
produzione solo se valgono entrambe:

- **(a)** nel gruppo "esclusa" l'IC 95% di `f − p_m` è tutto sotto zero;
- **(b)** l'IC 95% della differenza (`f − p_m` del gruppo "passa") −
  (`f − p_m` del gruppo "esclusa") è tutto sopra zero.

In ogni altro caso il filtro non si adotta e lo scarto resta un'informazione
di contesto.

Le tabelle su fasce di `p_m`, regressione logistica e incrocio con la colonna
"d'accordo" sono di contesto: non entrano nella regola. Le soglie 0,75 / 0,05
e i bordi delle fasce non vengono toccati dopo aver visto i dati.
"""


# ---------------------------------------------------------------------------\
# Bootstrap a blocchi (lega x stagione x data) e statistiche di gruppo
# ---------------------------------------------------------------------------
def draw_counts(nb: int, reps: int, rng) -> np.ndarray:
    idx = rng.integers(0, nb, size=(reps, nb))
    flat = (idx + np.arange(reps)[:, None] * nb).ravel()
    return np.bincount(flat, minlength=reps * nb).reshape(reps, nb).astype(float)


def block_keys(d: pd.DataFrame) -> np.ndarray:
    giorni = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
    return (d["league"].astype(str) + "|" + d["season"].astype(str) + "|" + giorni).to_numpy()


def ci_percentile(draws) -> tuple[float, float]:
    v = np.asarray(draws, float)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return (float("nan"), float("nan"))
    lo, hi = np.percentile(v, [2.5, 97.5])
    return float(lo), float(hi)


class BootstrapBlocchi:
    """Draw di blocchi condivisi fra tutte le statistiche del referto."""

    def __init__(self, d: pd.DataFrame, reps: int, seed: int):
        self.codes, uniq = pd.factorize(block_keys(d), sort=True)
        self.nb = len(uniq)
        self.reps = reps
        rng = np.random.default_rng(seed)
        self.cnt = draw_counts(self.nb, reps, rng) if reps else None
        self.rows_by_block = [np.flatnonzero(self.codes == b) for b in range(self.nb)]

    def delta_gruppo(self, y, pm, mask):
        """(f − p_m) del gruppo: punto, IC e draw bootstrap."""
        y = np.asarray(y, float)
        pm = np.asarray(pm, float)
        mask = np.asarray(mask, bool)
        n_g = np.bincount(self.codes[mask], minlength=self.nb).astype(float)
        y_g = np.bincount(self.codes[mask], weights=y[mask], minlength=self.nb)
        p_g = np.bincount(self.codes[mask], weights=pm[mask], minlength=self.nb)
        pt = float(y[mask].mean() - pm[mask].mean()) if mask.any() else float("nan")
        f_pt = float(y[mask].mean()) if mask.any() else float("nan")
        pm_pt = float(pm[mask].mean()) if mask.any() else float("nan")
        if self.cnt is None:
            return {"punto": pt, "f": f_pt, "p_m": pm_pt, "ic": (float("nan"),) * 2,
                    "draws": np.full(self.reps or 0, np.nan)}
        den = self.cnt @ n_g
        with np.errstate(divide="ignore", invalid="ignore"):
            draws = (self.cnt @ y_g) / den - (self.cnt @ p_g) / den
        draws[~np.isfinite(draws)] = np.nan
        return {"punto": pt, "f": f_pt, "p_m": pm_pt, "ic": ci_percentile(draws),
                "draws": draws}

    def diff_gruppi(self, info_a, info_b):
        """(f−p_m)_a − (f−p_m)_b appaiata sugli stessi draw."""
        draws = np.asarray(info_a["draws"]) - np.asarray(info_b["draws"])
        punto = float(info_a["punto"] - info_b["punto"])
        return {"punto": punto, "ic": ci_percentile(draws), "draws": draws}

    def righe_indices(self, rep: int) -> np.ndarray:
        pick = np.flatnonzero(self.cnt[rep]).astype(int)
        mult = self.cnt[rep, pick].astype(int)
        return np.concatenate([np.repeat(self.rows_by_block[b], m)
                               for b, m in zip(pick, mult)]) if pick.size else np.zeros(0, int)


# ---------------------------------------------------------------------------\
# Regressione logistica (IRLS) e bootstrap dei coefficienti
# ---------------------------------------------------------------------------
def logit_fit(X: np.ndarray, y: np.ndarray, max_iter: int = 60, tol: float = 1e-10):
    """MLE logistico con Newton-Raphson; None se non converge o matrice singolare."""
    beta = np.zeros(X.shape[1], float)
    for _ in range(max_iter):
        eta = np.clip(X @ beta, -30, 30)
        p = 1.0 / (1.0 + np.exp(-eta))
        w = np.clip(p * (1.0 - p), 1e-10, None)
        score = X.T @ (y - p)
        info = (X.T * w) @ X
        try:
            step = np.linalg.solve(info, score)
        except np.linalg.LinAlgError:
            return None
        beta_new = beta + step
        if not np.all(np.isfinite(beta_new)):
            return None
        if np.max(np.abs(beta_new - beta)) < tol:
            return beta_new
        beta = beta_new
    return beta


def bootstrap_coeff(boot: BootstrapBlocchi, X: np.ndarray, y: np.ndarray, reps: int):
    """Punto + IC a blocchi dei coefficienti; salta le repliche non convergenti."""
    punto = logit_fit(X, y)
    draws = np.full((reps, X.shape[1]), np.nan)
    for r in range(reps):
        ix = boot.righe_indices(r)
        if ix.size == 0 or np.unique(y[ix]).size < 2:
            continue
        b = logit_fit(X[ix], y[ix])
        if b is not None:
            draws[r] = b
    ic = [ci_percentile(draws[:, j]) for j in range(X.shape[1])]
    n_ok = int(np.isfinite(draws[:, 0]).sum())
    return punto, ic, n_ok


def logit(p: float) -> float:
    p = min(max(float(p), 1e-9), 1.0 - 1e-9)
    return float(np.log(p / (1.0 - p)))


def valuta_regola(ic_esclusa, ic_diff) -> tuple[bool, bool]:
    """Regola dichiarata (a)(b): IC 95% di f−p_m dell'esclusa tutto sotto zero;
    IC 95% della differenza passa−esclusa tutto sopra zero."""
    a_ok = bool(np.isfinite(ic_esclusa[1]) and ic_esclusa[1] < 0)
    b_ok = bool(np.isfinite(ic_diff[0]) and ic_diff[0] > 0)
    return a_ok, b_ok


# ---------------------------------------------------------------------------\
# Caricamento del campione (stesse funzioni di produzione del replay PR #49)
# ---------------------------------------------------------------------------
def carica_scelte() -> tuple[pd.DataFrame, dict]:
    import replay_topmix_mercato as RTM
    frame = RTM.costruisci_frame(usare_cache=True)
    campione = RTM.campionatura(frame)
    righe, max_scarto = RTM.applica_selettore(campione)
    scelte = righe[righe["ammessa"]].copy().reset_index(drop=True)
    scelte["p_m"] = scelte["prob_mercato"].astype(float)
    scelte["p_d"] = scelte["prob_modello"].astype(float)
    scelte["scarto"] = scelte["p_d"] - scelte["p_m"]
    scelte["y"] = scelte["vincente"].astype(float)
    scelte["alta"] = scelte["p_m"] >= SOGLIA_ALTA
    scelte["passa_scarto"] = scelte["scarto"].abs() <= TOLLERANZA_SCARTO
    scelte["passa"] = scelte["alta"] | scelte["passa_scarto"]
    scelte["esclusa"] = ~scelte["passa"]
    scelte["esclusa_alta"] = scelte["esclusa"] & (scelte["scarto"] > TOLLERANZA_SCARTO)
    scelte["esclusa_bassa"] = scelte["esclusa"] & (scelte["scarto"] < -TOLLERANZA_SCARTO)
    meta = {"righe_campione": int(len(righe)), "scelte": int(len(scelte)),
            "max_scarto_devig": float(max_scarto),
            "n_accordo": int(scelte["accordo"].astype(bool).sum())}
    assert len(scelte) == 1302, f"attese 1302 scelte di mercato, ottenute {len(scelte)}"
    return scelte, meta


def gruppi_tabelle(d: pd.DataFrame, base=None) -> "OrderedDict[str, np.ndarray]":
    """Gruppi della tabella 1/2 come maschere a lunghezza piena sul frame `d`.

    `base` restringe tutto (serve per le fasce di p_m della tabella 2).
    """
    base = np.ones(len(d), bool) if base is None else np.asarray(base, bool)
    low = (d["p_m"] < SOGLIA_ALTA).to_numpy() & base
    scarto = d["scarto"].to_numpy(float)
    esclusa = d["esclusa"].to_numpy() & base
    return OrderedDict([
        ("passa (|scarto| ≤ 0,05)", low & (np.abs(scarto) <= TOLLERANZA_SCARTO)),
        ("esclusa (|scarto| > 0,05)", esclusa),
        ("esclusa — modello più alto (scarto > +0,05)", esclusa & (scarto > TOLLERANZA_SCARTO)),
        ("esclusa — modello più basso (scarto < −0,05)", esclusa & (scarto < -TOLLERANZA_SCARTO)),
    ])


def riga_tabella(nome: str, mask, y, pm, boot: BootstrapBlocchi):
    info = boot.delta_gruppo(y, pm, mask)
    n = int(np.asarray(mask).sum())
    return {"gruppo": nome, "n": n, "p_m": info["p_m"],
            "f": info["f"], "delta": info["punto"], "ic": info["ic"], "_info": info}


# ---------------------------------------------------------------------------\
# Report
# ---------------------------------------------------------------------------
def _f(x, nd=4):
    if x is None or not np.isfinite(x):
        return "n/d"
    return f"{float(x):.{nd}f}".replace(".", ",")


def _pct(x, nd=2):
    if x is None or not np.isfinite(x):
        return "n/d"
    return f"{100 * float(x):.{nd}f}".replace(".", ",") + " %"


def _pt(x, nd=2):
    if x is None or not np.isfinite(x):
        return "n/d"
    return f"{100 * float(x):.{nd}f}".replace(".", ",") + " pt"


def _tab(headers, rows):
    head = "| " + " | ".join(headers) + " |"
    sep = "|" + "|".join(["---"] * len(headers)) + "|"
    return "\n".join([head, sep] + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def _riga_stat(nome, r):
    ic = r["ic"]
    return (f"| {nome} | {r['n']} | {_pct(r['p_m'])} | {_pct(r['f'])} | "
            f"{_pt(r['delta'])} | [{_pt(ic[0])}; {_pt(ic[1])}] |")


def scrivi_referto(payload: dict) -> str:
    P = [RULE_TEXT.rstrip(), ""]
    P.append(f"Generato da `audit/filtro_concordanza_scarto.py` il {payload['generato_il']} "
             f"(commit `{payload['git']['commit']}`, branch `{payload['git']['branch']}`). "
             f"Bootstrap: {payload['reps']} repliche a blocchi lega × stagione × data, "
             f"seme {payload['seed']}. Nessuna rete, nessuna modifica a `SoccerMath/`.\n")

    m = payload["meta"]
    P.append(f"Replay di provenienza in parità con la PR #49: "
             f"**{'SÌ' if payload['parita_replay'] else 'NO'}** "
             f"({m['scelte']} scelte di mercato su {m['righe_campione']} righe di campione; "
             f"max scarto de-vig vs colonne `pre*` PR #49: {m['max_scarto_devig']:.2e}).\n")

    # ---- Tabella 1 ----
    P.append("## 1. Gruppi passa / esclusa (solo scelte con p_m < 0,75)\n")
    P.append("| gruppo | n | p_m media | frequenza di vincita f | f − p_m | IC 95% a blocchi |")
    P.append("|---|---:|---:|---:|---:|---|")
    for r in payload["tabella1"]:
        P.append(_riga_stat(r["gruppo"], r))
    r = payload["alta_definizione"]
    P.append("")
    P.append(f"Informazione (fuori regola): le scelte con `p_m ≥ 0,75` passano per "
             f"definizione: n = {r['n']}, p_m media {_pct(r['p_m'])}, f = {_pct(r['f'])}, "
             f"f − p_m = {_pt(r['delta'])} [{_pt(r['ic'][0])}; {_pt(r['ic'][1])}].\n")

    # ---- Tabella 2 ----
    P.append("## 2. Stessa tabella dentro le fasce di p_m\n")
    P.append("| fascia | gruppo | n | p_m media | f | f − p_m | IC 95% a blocchi |")
    P.append("|---|---|---:|---:|---:|---:|---|")
    for fascia in payload["tabella2"]:
        for r in fascia["righe"]:
            P.append(f"| {fascia['fascia']} | {r['gruppo']} | {r['n']} | {_pct(r['p_m'])} | "
                     f"{_pct(r['f'])} | {_pt(r['delta'])} | "
                     f"[{_pt(r['ic'][0])}; {_pt(r['ic'][1])}] |")
    P.append("")

    # ---- Tabella 3 ----
    P.append("## 3. Regressione logistica dell'esito (1 = vinta)\n")
    P.append("Modello A: `logit P(vinta) = b0 + b1 · logit(p_m) + b2 · scarto`. "
             "Modello B: scarto diviso in parte positiva `max(scarto, 0)` e parte "
             "negativa `min(scarto, 0)`. IC 95% dallo stesso bootstrap a blocchi.\n")
    P.append("| modello | coefficiente | stima | IC 95% a blocchi | repliche valide |")
    P.append("|---|---|---:|---|---:|")
    for modello in payload["tabella3"]:
        for coef in modello["coefficienti"]:
            P.append(f"| {modello['modello']} | {coef['nome']} | {_f(coef['stima'])} | "
                     f"[{_f(coef['ic'][0])}; {_f(coef['ic'][1])}] | {modello['repliche_valide']} |")
    P.append("")

    # ---- Tabella 4 ----
    P.append("## 4. Incrocio con la colonna \"d'accordo\" di produzione\n")
    P.append("Colonna `accordo` del selettore di produzione: modello e mercato sullo "
             "stesso esito ed entrambi ≥ 0,55 (`market_odds.SOGLIA_ACCORDO`).\n")
    P.append("| gruppo | n | p_m media | f | f − p_m | IC 95% a blocchi |")
    P.append("|---|---:|---:|---:|---:|---|")
    for r in payload["tabella4"]:
        P.append(_riga_stat(r["gruppo"], r))
    P.append("")
    P.append(payload["tabella4_nota"] + "\n")

    # ---- Tabella 5 ----
    P.append("## 5. Hit rate prima e dopo il filtro (solo descrittivo)\n")
    P.append("| insieme | n | vinte | hit rate |")
    P.append("|---|---:|---:|---:|")
    for r in payload["tabella5"]:
        P.append(f"| {r['insieme']} | {r['n']} | {r['vinte']} | {_pct(r['hit'])} |")
    P.append("")
    P.append(f"Scelte perse dal filtro: **{payload['scelte_perse']}** "
             f"(hit rate {_pct(payload['hit_perse'])}).\n")

    # ---- Esito regola ----
    P.append("## 6. Esito della regola (a)(b)\n")
    e = payload["esito_regola"]
    P.append(_tab(["condizione", "misura", "IC 95% a blocchi", "esito"],
                  [[r["condizione"], r["misura"], r["ic"], r["esito"]] for r in e["righe"]]))
    P.append("")
    P.append(f"**Verdetto: {e['verdetto']}** — {e['frase']}\n")
    P.append(f"Sensibilità (gruppo \"passa\" esteso a tutte le scelte mantenute dal "
             f"filtro, incluse `p_m ≥ 0,75`): differenza (f − p_m) = "
             f"{_pt(e['sensibilita']['punto'])} [{_pt(e['sensibilita']['ic'][0])}; "
             f"{_pt(e['sensibilita']['ic'][1])}]; condizione (b) "
             f"{'superata' if e['sensibilita']['b_ok'] else 'non superata'} anche in "
             f"questa lettura. Il verdetto resta quello della definizione principale.\n")

    # ---- Limiti ----
    P.append("## 7. Limiti dichiarati\n")
    for l in payload["limiti"]:
        P.append(f"- {l}")
    P.append("")
    return "\n".join(P)


# ---------------------------------------------------------------------------\
# Main
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reps", type=int, default=DEFAULT_REPS)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--report", default=REPORT_PATH)
    ap.add_argument("--json", default=JSON_PATH)
    args = ap.parse_args(argv)

    scelte, meta = carica_scelte()
    y = scelte["y"].to_numpy(float)
    pm = scelte["p_m"].to_numpy(float)
    boot = BootstrapBlocchi(scelte, args.reps, args.seed)

    # parita' del replay di provenienza (i numeri PR #49 sono gia' verificati dal
    # replay dedicato; qui si controlla solo la cardinalita' del campione)
    parita_replay = meta["scelte"] == 1302

    # ---- Tabella 1 ----
    t1 = []
    info_t1 = {}
    for nome, mask in gruppi_tabelle(scelte).items():
        r = riga_tabella(nome, mask, y, pm, boot)
        info_t1[nome] = r.pop("_info")
        t1.append(r)
    alta = riga_tabella("p_m ≥ 0,75 (passa per definizione)",
                        scelte["alta"].to_numpy(), y, pm, boot)
    alta_info = alta.pop("_info")

    # ---- Tabella 2 ----
    t2 = []
    for lo, hi in FASCE_PM:
        base = ((scelte["p_m"] >= lo) & (scelte["p_m"] < hi)).to_numpy()
        etichetta = f"[{lo:.2f}-{hi:.2f})".replace(".", ",")
        righe = []
        for nome, mask in gruppi_tabelle(scelte, base=base).items():
            r = riga_tabella(nome, mask, y, pm, boot)
            r.pop("_info")
            righe.append(r)
        t2.append({"fascia": etichetta, "righe": righe})

    # ---- Tabella 3: regressione logistica ----
    x_logit = np.array([logit(p) for p in pm], float)
    scarto = scelte["scarto"].to_numpy(float)
    X_A = np.column_stack([np.ones(len(scelte)), x_logit, scarto])
    nomi_A = ["b0 (costante)", "b1 logit(p_m)", "b2 scarto"]
    X_B = np.column_stack([np.ones(len(scelte)), x_logit,
                           np.maximum(scarto, 0.0), np.minimum(scarto, 0.0)])
    nomi_B = ["b0 (costante)", "b1 logit(p_m)", "b2 scarto positivo max(s,0)",
              "b3 scarto negativo min(s,0)"]
    t3 = []
    for nome_modello, X, nomi in (("A: y ~ logit(p_m) + scarto", X_A, nomi_A),
                                  ("B: y ~ logit(p_m) + scarto⁺ + scarto⁻", X_B, nomi_B)):
        punto, ic, n_ok = bootstrap_coeff(boot, X, y, args.reps)
        coefficienti = []
        for j, nome in enumerate(nomi):
            coefficienti.append({"nome": nome,
                                 "stima": (float(punto[j]) if punto is not None else None),
                                 "ic": list(ic[j])})
        t3.append({"modello": nome_modello, "coefficienti": coefficienti,
                   "repliche_valide": n_ok})

    # ---- Tabella 4: incrocio con "d'accordo" ----
    acc = scelte["accordo"].astype(bool).to_numpy()
    escl = scelte["esclusa"].to_numpy()
    t4 = []
    for nome, mask in (
            ("escluse già \"senza accordo\" (accordo = False)", escl & ~acc),
            ("escluse \"d'accordo\" (accordo = True)", escl & acc),
            ("tutte le escluse", escl)):
        r = riga_tabella(nome, mask, y, pm, boot)
        r.pop("_info")
        t4.append(r)
    n_escluse_senza = int((escl & ~acc).sum())
    n_escluse_con = int((escl & acc).sum())
    t4_nota = (f"Delle {int(escl.sum())} escluse, **{n_escluse_senza}** hanno già la "
               f"colonna \"d'accordo\" a False (il filtro non aggiungerebbe nulla su "
               f"queste) e **{n_escluse_con}** sono \"d'accordo\": il loro "
               f"f − p_m è quello della seconda riga.")

    # ---- Tabella 5: hit rate prima/dopo ----
    passa_all = scelte["passa"].to_numpy()
    perse = escl
    t5 = [
        {"insieme": "insieme completo (scelte di mercato)", "n": int(len(scelte)),
         "vinte": int(y.sum()), "hit": float(y.mean())},
        {"insieme": "dopo il filtro (solo scelte che passano)", "n": int(passa_all.sum()),
         "vinte": int(y[passa_all].sum()),
         "hit": float(y[passa_all].mean()) if passa_all.any() else float("nan")},
        {"insieme": "scelte perse (escluse)", "n": int(perse.sum()),
         "vinte": int(y[perse].sum()),
         "hit": float(y[perse].mean()) if perse.any() else float("nan")},
    ]

    # ---- Esito della regola (a)(b) ----
    info_escl = info_t1["esclusa (|scarto| > 0,05)"]
    info_pass = info_t1["passa (|scarto| ≤ 0,05)"]
    diff = boot.diff_gruppi(info_pass, info_escl)
    a_ok, b_ok = valuta_regola(info_escl["ic"], diff["ic"])
    # sensibilita': passa esteso (incluse p_m >= 0,75)
    info_pass_esteso = boot.delta_gruppo(y, pm, passa_all)
    diff_esteso = boot.diff_gruppi(info_pass_esteso, info_escl)
    _, b_ok_esteso = valuta_regola(info_escl["ic"], diff_esteso["ic"])

    if a_ok and b_ok:
        verdetto = "IL FILTRO SI PROPONE PER LA PRODUZIONE"
        frase = ("condizioni (a) e (b) entrambe soddisfatte secondo la regola "
                 "dichiarata; resta da decidere in produzione, che non è toccata da "
                 "questo audit.")
    else:
        verdetto = "IL FILTRO NON SI ADOTTA"
        mancanti = [c for c, ok in (("(a)", a_ok), ("(b)", b_ok)) if not ok]
        verbo = "non vale" if len(mancanti) == 1 else "non valgono"
        frase = (f"{verbo} " + " e ".join(mancanti) + ": lo scarto resta "
                 "un'informazione di contesto, come da regola dichiarata.")

    esito_regola = {
        "righe": [
            {"condizione": "(a) IC 95% di f − p_m del gruppo \"esclusa\" tutto sotto zero",
             "misura": f"f − p_m = {_pt(info_escl['punto'])}",
             "ic": f"[{_pt(info_escl['ic'][0])}; {_pt(info_escl['ic'][1])}]",
             "esito": "SUPERATA" if a_ok else "NON SUPERATA"},
            {"condizione": "(b) IC 95% di (f − p_m)passa − (f − p_m)esclusa tutto sopra zero",
             "misura": f"differenza = {_pt(diff['punto'])}",
             "ic": f"[{_pt(diff['ic'][0])}; {_pt(diff['ic'][1])}]",
             "esito": "SUPERATA" if b_ok else "NON SUPERATA"},
        ],
        "verdetto": verdetto, "frase": frase,
        "a_ok": a_ok, "b_ok": b_ok,
        "sensibilita": {"punto": diff_esteso["punto"],
                        "ic": list(diff_esteso["ic"]), "b_ok": b_ok_esteso},
    }

    payload = {
        "generato_il": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git": _git_facts(),
        "reps": args.reps, "seed": args.seed,
        "parita_replay": bool(parita_replay),
        "meta": meta,
        "soglie": {"p_m_alta": SOGLIA_ALTA, "tolleranza_scarto": TOLLERANZA_SCARTO,
                   "fasce_pm": [list(f) for f in FASCE_PM]},
        "tabella1": t1, "alta_definizione": alta,
        "tabella2": t2, "tabella3": t3,
        "tabella4": t4, "tabella4_nota": t4_nota,
        "tabella5": t5,
        "scelte_perse": int(perse.sum()),
        "hit_perse": float(y[perse].mean()) if perse.any() else None,
        "esito_regola": esito_regola,
        "limiti": list(LIMITI),
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.report)), exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1, default=str)
    referto = scrivi_referto(payload)
    with open(args.report, "w", encoding="utf-8") as fh:
        fh.write(referto)
    print(referto)
    print(f"\njson:    {args.json}")
    print(f"referto: {args.report}")
    print(f"\n[esito regola] {verdetto}")
    return 0


def _git_facts() -> dict:
    def run(*cmd):
        try:
            return subprocess.run(cmd, cwd=_REPO_ROOT, capture_output=True, text=True,
                                  timeout=30).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    return {"commit": run("git", "rev-parse", "--short", "HEAD"),
            "branch": run("git", "rev-parse", "--abbrev-ref", "HEAD")}


if __name__ == "__main__":
    raise SystemExit(main())
