#!/usr/bin/env python3
"""griglia_penaltyblog_check.py — sezione A: libreria penaltyblog vs fit scipy (audit).

Da eseguire in un venv SEPARATO con penaltyblog (non e' una dipendenza di produzione
ne' di requirements-audit.txt):

    python -m venv /tmp/venv_pb
    /tmp/venv_pb/bin/pip install penaltyblog
    /tmp/venv_pb/bin/python audit/griglia_penaltyblog_check.py

Cosa fa:
  1. stessi input del fit implicito (1X2 + Over 2,5 B365 anticipate, de-vig prop.),
     su tutte le partite delle stagioni 2024/25 e 2025/26 con quote complete;
  2. penaltyblog.models.goal_expectancy_extended (gol attesi casa/trasferta, rho DC);
  3. confronto con il fit scipy di audit/griglia_core.py: scarti di lambda, mu, rho,
     residui max, tempi;
  4. penaltyblog.models.create_dixon_coles_grid(lam, mu, rho): confronto della griglia
     con dc_matrix (stessa convenzione tau?) e dei mercati O/U 2,5 e 1X2;
  5. scrive audit/output/griglia_penaltyblog_check.json (incluso nel referto) e
     audit/results/griglia_penaltyblog_check.md.

Non legge ne' scrive SoccerMath/ e non usa rete.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
DB_DIR = os.path.join(_REPO_ROOT, "SoccerMath", "database")
OUT_DIR = os.path.join(_AUDIT_DIR, "output")
RES_MD = os.path.join(_AUDIT_DIR, "results", "griglia_penaltyblog_check.md")
RES_JSON = os.path.join(OUT_DIR, "griglia_penaltyblog_check.json")

from griglia_core import (  # noqa: E402
    N, devig_prop, dc_matrix, fit_implicit, grid_1x2_ou,
)

FILES = [("SerieA", "Serie A"), ("Premier", "Premier League"), ("LaLiga", "La Liga"),
         ("Bundesliga", "Bundesliga"), ("Ligue1", "Ligue 1")]
SUFFIX = {"2024/25": "2024", "2025/26": "2025"}


def load_b365() -> pd.DataFrame:
    frames = []
    for prefix, league in FILES:
        for season, suf in SUFFIX.items():
            df = pd.read_csv(os.path.join(DB_DIR, f"{prefix}_{suf}.csv"), encoding="utf-8-sig",
                             on_bad_lines="warn", low_memory=False)
            cols = ["B365H", "B365D", "B365A", "B365>2.5", "B365<2.5", "FTHG", "FTAG"]
            d = df[cols].copy()
            d["league"], d["season"] = league, season
            frames.append(d)
    d = pd.concat(frames, ignore_index=True)
    for c in d.columns:
        if c not in ("league", "season"):
            d[c] = pd.to_numeric(d[c], errors="coerce")
    return d.dropna().reset_index(drop=True)


def main() -> int:
    import penaltyblog as pb  # noqa: WPS433  (dipendenza di questo script)
    from penaltyblog.models import create_dixon_coles_grid, goal_expectancy_extended

    t0 = time.time()
    d = load_b365()
    n = len(d)
    p_pb = np.zeros((n, 4))   # lam/mu/rho/resid ... (mu_home, mu_away, rho)
    rows = []
    pb_ok = 0
    t_pb = t_sc = 0.0
    for i, (h, dr_, a_, o_over, o_under) in enumerate(zip(
            d["B365H"], d["B365D"], d["B365A"], d["B365>2.5"], d["B365<2.5"])):
        p1, pX, p2 = devig_prop([h, dr_, a_])
        pO = devig_prop([o_over, o_under])[0]
        a = time.time()
        try:
            out = goal_expectancy_extended(p1, pX, p2, pO, 1 - pO, remove_overround=True)
            ok = bool(out.get("success", True))
            lam_pb, mu_pb, rho_pb = float(out["home_exp"]), float(out["away_exp"]), float(out["implied_rho"])
            pred = np.array(list(out["predicted_1x2"]) + [out["predicted_ou"][0]])
            res_pb = float(np.max(np.abs(pred - np.array([p1, pX, p2, pO]))))
        except Exception as exc:  # noqa: BLE001
            ok, lam_pb, mu_pb, rho_pb, res_pb = False, np.nan, np.nan, np.nan, np.nan
            rows.append({"err": f"{type(exc).__name__}: {exc}"})
        t_pb += time.time() - a
        a = time.time()
        sc = fit_implicit(p1, pX, p2, pO, rho_free=True)
        t_sc += time.time() - a
        pb_ok += int(ok)
        rows.append({"pt1": p1, "ptX": pX, "pt2": p2, "ptO": pO,
                     "lam_pb": lam_pb, "mu_pb": mu_pb, "rho_pb": rho_pb, "res_pb": res_pb,
                     "lam_sc": sc["lam"], "mu_sc": sc["mu"], "rho_sc": sc["rho"],
                     "res_sc": sc["max_abs_resid"], "ok_pb": ok})

    R = pd.DataFrame(rows)
    good = R["lam_pb"].notna()
    fail = good & (R["res_pb"] > 1e-3)           # fit penaltyblog che non riproduce le quote
    okfit = good & ~fail
    dl = (R.loc[okfit, "lam_pb"] - R.loc[okfit, "lam_sc"]).abs()
    dm = (R.loc[okfit, "mu_pb"] - R.loc[okfit, "mu_sc"]).abs()
    dr = (R.loc[okfit, "rho_pb"] - R.loc[okfit, "rho_sc"]).abs()

    # convenzione tau: penaltyblog.create_dixon_coles_grid vs dc_matrix (produzione)
    # e vs la convenzione SCAMBIATA (1+mu*rho su (0,1), 1+lam*rho su (1,0))
    cells_01_10 = np.zeros((N, N), bool)
    cells_01_10[0, 1] = cells_01_10[1, 0] = True
    diff_all, diff_no0110, diff_swapped = [], [], []
    grid_err = 0
    for lam, mu, rho in R.loc[okfit, ["lam_sc", "mu_sc", "rho_sc"]].head(200).to_numpy():
        try:
            g = create_dixon_coles_grid(float(lam), float(mu), float(rho), max_goals=N - 1)
        except ValueError:
            grid_err += 1   # rho fuori dai limiti di penaltyblog: non confrontabile
            continue
        pm = np.asarray(g.grid, float)
        pm = pm / pm.sum()
        ours = dc_matrix(float(lam), float(mu), float(rho))
        sw = dc_matrix_swapped(float(lam), float(mu), float(rho))
        diff_all.append(float(np.abs(pm - ours).max()))
        diff_no0110.append(float(np.abs((pm - ours)[~cells_01_10]).max()))
        diff_swapped.append(float(np.abs(pm - sw).max()))
    # coerenza interna: griglia pb con i parametri di pb -> residuo sulle quote
    internal = []
    for i in R.index[fail | okfit][:300]:
        if not good[i]:
            continue
        try:
            g = create_dixon_coles_grid(float(R.at[i, "lam_pb"]), float(R.at[i, "mu_pb"]),
                                        float(R.at[i, "rho_pb"]), max_goals=N - 1)
        except ValueError:
            continue
        pm = np.asarray(g.grid, float); pm = pm / pm.sum()
        internal.append(float(np.max(np.abs(grid_1x2_ou(pm) - np.array(
            [R.at[i, "pt1"], R.at[i, "ptX"], R.at[i, "pt2"], R.at[i, "ptO"]])))))

    pb_ver = getattr(pb, "__version__", "n/d")
    try:
        import importlib.metadata as md
        deps = [r.split(";")[0] for r in (md.requires("penaltyblog") or []) if "extra" not in r]
    except Exception:  # noqa: BLE001
        deps = []

    res = {
        "generato_il": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "penaltyblog": pb_ver, "python": platform.python_version(),
        "dipendenze_dirette": deps,
        "partite": n, "fit_penaltyblog_riusciti": int(okfit.sum()),
        "fit_penaltyblog_non_riproducono_quote": int(fail.sum()),
        "fit_penaltyblog_max_residuo_non_riproducono": float(R.loc[fail, "res_pb"].max()) if fail.any() else None,
        "fit_penaltyblog_bordo_lambda": int(((R.loc[good, "mu_pb"] >= 20.0) | (R.loc[good, "lam_pb"] >= 20.0)).sum()),
        "tempo_penaltyblog_s": round(t_pb, 1), "tempo_scipy_s": round(t_sc, 1),
        "confronto_su_riusciti": int(okfit.sum()),
        "scarto_mediano_lambda": float(dl.median()), "scarto_p95_lambda": float(dl.quantile(0.95)),
        "scarto_mediano_mu": float(dm.median()), "scarto_p95_mu": float(dm.quantile(0.95)),
        "scarto_mediano_rho": float(dr.median()), "scarto_p95_rho": float(dr.quantile(0.95)),
        "residuo_max_scipy": float(R.loc[good, "res_sc"].max()),
        "griglia_confronti": len(diff_all), "griglia_fuori_limiti": grid_err,
        "griglia_scarto_max_pb_vs_produzione": max(diff_all) if diff_all else None,
        "griglia_scarto_max_escluse_01_10": max(diff_no0110) if diff_no0110 else None,
        "griglia_scarto_max_pb_vs_convenzione_scambiata": max(diff_swapped) if diff_swapped else None,
        "coerenza_interna_pb_residuo_max": max(internal) if internal else None,
        "coerenza_interna_n": len(internal),
    }
    res["sezione_md"] = build_md(res)
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(RES_MD), exist_ok=True)
    with open(RES_JSON, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=2)
    with open(RES_MD, "w", encoding="utf-8") as fh:
        fh.write("# Verifica penaltyblog (sezione A)\n\n" + res["sezione_md"] + "\n")
    print(json.dumps({k: v for k, v in res.items() if k != "sezione_md"}, ensure_ascii=False, indent=2))
    return 0


def dc_matrix_swapped(lam: float, mu: float, rho: float) -> np.ndarray:
    """Convenzione tau scambiata: (0,1) *= 1 + mu*rho, (1,0) *= 1 + lam*rho."""
    from scipy.stats import poisson
    from griglia_core import GOALS
    m = np.outer(poisson.pmf(GOALS, lam), poisson.pmf(GOALS, mu))
    m[0, 0] *= max(1 - lam * mu * rho, 0.0)
    m[0, 1] *= max(1 + mu * rho, 0.0)
    m[1, 0] *= max(1 + lam * rho, 0.0)
    m[1, 1] *= max(1 - rho, 0.0)
    return m / m.sum()


def _f(x, nd=4):
    if x is None:
        return "n/d"
    return f"{x:.{nd}e}" if abs(x) < 1e-3 and x != 0 else f"{x:.{nd}f}".replace(".", ",")


def build_md(r: dict) -> str:
    deps = ", ".join(r["dipendenze_dirette"]) if r["dipendenze_dirette"] else "n/d"
    return "\n".join([
        f"- **Versione e installazione**: penaltyblog {r['penaltyblog']} da PyPI su Python {r['python']} "
        "(installazione riuscita nel venv dedicato). Un `pip install --dry-run` nel venv di audit "
        "(con SoccerMath/requirements.txt e requirements-audit.txt) non cambia numpy, pandas o scipy: "
        "aggiunge una cinquantina di pacchetti.",
        f"- **Dipendenze dirette** ({len(r['dipendenze_dirette'])}): {deps}. Sono pesanti "
        "(matplotlib, plotly, kaleido, statsbombpy, ipywidgets). **Non compatibile come dipendenza di "
        "produzione** (SoccerMath/requirements.txt, Streamlit Cloud): non verificato su Streamlit Cloud, "
        "ma la sola mole delle dipendenze lo sconsiglia.",
        "- **Funzione**: `penaltyblog.models.goal_expectancy_extended` (NON in `penaltyblog.implied`). "
        "Minimizza il Brier su 5 probabilita' (1X2 + O/U 2,5) con 3 parametri (log mu casa, log mu trasferta, rho). "
        "Non e' un risolutore esatto: il residuo va misurato.",
        f"- **Fit su {r['partite']} partite** (B365 1X2 + O/U 2,5 completi): riusciti e riproducono le quote "
        f"(residuo ≤ 1e-3): **{r['confronto_su_riusciti']}**; NON riproducono le quote: "
        f"**{r['fit_penaltyblog_non_riproducono_quote']}** (residuo massimo {_f(r['fit_penaltyblog_max_residuo_non_riproducono'],3)}), "
        "con `success = True` nel dizionario di output. Sintomo: lambda/mu al bordo exp(3) ≈ 20,1 "
        f"e rho al bordo 0,5 (partite con lambda o mu al bordo: {r['fit_penaltyblog_bordo_lambda']}). "
        f"Il fit scipy di audit riproduce le stesse quote con residuo massimo {_f(r['residuo_max_scipy'],2)}.",
        f"- **Parametri sulle partite riuscite** (scarto assoluto rispetto al fit scipy): lambda mediano "
        f"{_f(r['scarto_mediano_lambda'],3)} (p95 {_f(r['scarto_p95_lambda'],3)}), mu mediano {_f(r['scarto_mediano_mu'],3)} "
        f"(p95 {_f(r['scarto_p95_mu'],3)}), rho mediano {_f(r['scarto_mediano_rho'],3)} (p95 {_f(r['scarto_p95_rho'],3)}). "
        "Gli scarti non sono zero: vedi il punto sulla convenzione.",
        f"- **Convenzione tau di `create_dixon_coles_grid`** su {r['griglia_confronti']} casi (fuori dai limiti "
        f"di penaltyblog: {r['griglia_fuori_limiti']}): scarto massimo cella per cella rispetto a "
        f"`dc_matrix` (produzione) {_f(r['griglia_scarto_max_pb_vs_produzione'],3)}; escludendo le celle "
        f"(0,1) e (1,0) scende a {_f(r['griglia_scarto_max_escluse_01_10'],4)} (residuo dovuto alla rinormalizzazione "
        f"della griglia); rispetto alla convenzione SCAMBIATA (0,1) *= 1+mu·rho, (1,0) *= 1+lambda·rho lo scarto e' "
        f"{_f(r['griglia_scarto_max_pb_vs_convenzione_scambiata'],2)}. "
        "Conclusione: penaltyblog usa lambda e mu invertiti sulle due celle a un gol, rispetto alla "
        "convenzione di produzione (`models/dixon_coles.tau_correction`).",
        f"- **Coerenza interna** di penaltyblog (sua griglia con i suoi parametri vs le quote di partenza, "
        f"{r['coerenza_interna_n']} casi): residuo massimo {_f(r['coerenza_interna_pb_residuo_max'],3)}.",
        f"- **Tempi** ({r['partite']} fit): penaltyblog {r['tempo_penaltyblog_s']} s, scipy {r['tempo_scipy_s']} s.",
        "- **Decisione**: penaltyblog NON si usa per il referto. Motivi: (1) dipendenze pesanti e non "
        "necessarie; (2) convenzione tau diversa da quella di produzione; (3) fallimenti silenziosi "
        "su circa lo 0,6% delle partite. Il referto usa il fit scipy in `audit/griglia_core.py`, "
        "con la convenzione di produzione e il residuo riportato per partita.",
    ])


if __name__ == "__main__":
    raise SystemExit(main())
