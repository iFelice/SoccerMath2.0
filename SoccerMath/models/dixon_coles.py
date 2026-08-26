"""
models/dixon_coles.py - Motore Statistico Dixon-Coles per M4-analist
Implementa:
- Stima di massima verosimiglianza delle forze di attacco (alpha) e difesa (beta)
- Decadimento temporale esponenziale (time-decay xi = 0.0019)
- Correzione di dipendenza per risultati a basso punteggio tau(x, y, rho)
- Matrice di probabilità dei punteggi esatti e mercati (1X2, U/O, GG/NG)
"""

import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

from config import (
    DATABASE_DIR,
    LEAGUES_CONFIG,
    LEAGUE_PREFIX_MAP,
    clean_name,
)
from models.elo_engine import EloEngine

# Costanti del Modello
DEFAULT_XI = 0.0019  # Parametro di decadimento temporale (half-life ~ 1 anno)
DEFAULT_MAX_GOALS = 8


def tau_correction(x: int, y: int, lam: float, mu: float, rho: float) -> float:
    """
    Funzione di correzione di correlazione per punteggi bassi di Dixon-Coles:
    - (0, 0): 1 - lam * mu * rho
    - (0, 1): 1 + lam * rho
    - (1, 0): 1 + mu * rho
    - (1, 1): 1 - rho
    - Altro: 1.0
    """
    if x == 0 and y == 0:
        val = 1.0 - (lam * mu * rho)
    elif x == 0 and y == 1:
        val = 1.0 + (lam * rho)
    elif x == 1 and y == 0:
        val = 1.0 + (mu * rho)
    elif x == 1 and y == 1:
        val = 1.0 - rho
    else:
        val = 1.0
    return max(val, 1e-6)


class DixonColesEngine:
    """
    Motore di stima e predizione basato sul modello Dixon & Coles (1997).
    """

    def __init__(self, league_name: str, xi: float = DEFAULT_XI):
        self.league_name = league_name
        self.xi = xi
        self.teams: List[str] = []
        self.team_idx: Dict[str, int] = {}
        self.attack_params: Dict[str, float] = {}
        self.defense_params: Dict[str, float] = {}
        self.home_advantage: float = 0.25  # In scala logaritmica (gamma)
        self.rho: float = -0.04           # Parametro di correlazione punteggi bassi
        self.is_fitted: bool = False
        self.df_matches: pd.DataFrame = pd.DataFrame()

    def fit(self, max_iter: int = 150) -> bool:
        """
        Calcola i parametri ottimali del modello massimizzando la verosimiglianza
        ponderata con il decadimento temporale.
        """
        # Carica le partite tramite EloEngine helper per coerenza sui file di lega
        elo_helper = EloEngine(self.league_name)
        df = elo_helper.load_and_preprocess_matches()

        if df.empty or len(df) < 20:
            return False

        self.df_matches = df
        teams_set = sorted(list(set(df["HomeClean"]).union(set(df["AwayClean"]))))
        self.teams = teams_set
        self.team_idx = {t: i for i, t in enumerate(teams_set)}
        n_teams = len(teams_set)

        # Calcolo pesi di decadimento temporale: w_k = exp(-xi * delta_days)
        max_date = df["Date_Parsed"].max()
        days_diff = (max_date - df["Date_Parsed"]).dt.days.values
        weights = np.exp(-self.xi * days_diff)

        home_indices = df["HomeClean"].map(self.team_idx).values
        away_indices = df["AwayClean"].map(self.team_idx).values
        fthg_arr = df["FTHG"].astype(int).values
        ftag_arr = df["FTAG"].astype(int).values

        mask_00 = (fthg_arr == 0) & (ftag_arr == 0)
        mask_01 = (fthg_arr == 0) & (ftag_arr == 1)
        mask_10 = (fthg_arr == 1) & (ftag_arr == 0)
        mask_11 = (fthg_arr == 1) & (ftag_arr == 1)

        def neg_log_likelihood(params):
            alphas = params[:n_teams]
            betas = params[n_teams : 2 * n_teams]
            gamma = params[2 * n_teams]
            rho = params[2 * n_teams + 1]

            lams = np.exp(alphas[home_indices] + betas[away_indices] + gamma)
            mus = np.exp(alphas[away_indices] + betas[home_indices])

            # Vettorizzazione del fattore tau
            tau_vals = np.ones(len(fthg_arr))
            tau_vals[mask_00] = 1.0 - lams[mask_00] * mus[mask_00] * rho
            tau_vals[mask_01] = 1.0 + lams[mask_01] * rho
            tau_vals[mask_10] = 1.0 + mus[mask_10] * rho
            tau_vals[mask_11] = 1.0 - rho
            tau_vals = np.maximum(tau_vals, 1e-6)

            # Log-Likelihood ponderata
            log_lams = np.log(np.maximum(lams, 1e-6))
            log_mus = np.log(np.maximum(mus, 1e-6))

            ll = weights * (
                np.log(tau_vals) - lams + fthg_arr * log_lams - mus + ftag_arr * log_mus
            )
            return -np.sum(ll)

        # Valori iniziali: alpha=0, beta=0, gamma=0.25, rho=-0.04
        init_params = np.zeros(2 * n_teams + 2)
        init_params[2 * n_teams] = 0.25
        init_params[2 * n_teams + 1] = -0.04

        # Vincolo di identificabilità: sum(alphas) = 0
        constraints = [{"type": "eq", "fun": lambda p: np.sum(p[:n_teams])}]
        bounds = [(-3.0, 3.0)] * (2 * n_teams) + [(0.0, 1.5), (-0.25, 0.25)]

        try:
            res = minimize(
                neg_log_likelihood,
                init_params,
                method="SLSQP",
                constraints=constraints,
                bounds=bounds,
                options={"maxiter": max_iter, "ftol": 1e-5},
            )

            if res.success or res.fun is not None:
                alphas_opt = res.x[:n_teams]
                betas_opt = res.x[n_teams : 2 * n_teams]
                self.home_advantage = float(res.x[2 * n_teams])
                self.rho = float(res.x[2 * n_teams + 1])

                for i, team in enumerate(teams_set):
                    self.attack_params[team] = float(alphas_opt[i])
                    self.defense_params[team] = float(betas_opt[i])

                self.is_fitted = True
                return True
        except Exception:
            pass

        # Fallback analitico se l'ottimizzazione numerica non converge
        self._analytical_fallback(df)
        self.is_fitted = True
        return True

    def _analytical_fallback(self, df: pd.DataFrame):
        """Stima rapida baseline delle forze di attacco e difesa se SLSQP fallisce."""
        avg_h = df["FTHG"].mean() if not df.empty else 1.4
        avg_a = df["FTAG"].mean() if not df.empty else 1.1

        self.home_advantage = math.log(max(avg_h / avg_a, 1.05)) if avg_a > 0 else 0.25
        self.rho = -0.04

        for team in self.teams:
            h_matches = df[df["HomeClean"] == team]
            a_matches = df[df["AwayClean"] == team]

            gf = h_matches["FTHG"].sum() + a_matches["FTAG"].sum()
            ga = h_matches["FTAG"].sum() + a_matches["FTHG"].sum()
            tot = max(1, len(h_matches) + len(a_matches))

            att = math.log(max((gf / tot) / max(avg_h, 0.1), 0.2))
            defe = math.log(max((ga / tot) / max(avg_a, 0.1), 0.2))

            self.attack_params[team] = att
            self.defense_params[team] = defe

    def predict_match(self, home_team: str, away_team: str, max_goals: int = DEFAULT_MAX_GOALS) -> dict:
        """
        Calcola i gol attesi (lambda, mu) e la matrice congiunta di probabilità Dixon-Coles.
        """
        if not self.is_fitted:
            self.fit()

        h_cl = clean_name(home_team)
        a_cl = clean_name(away_team)

        alpha_h = self.attack_params.get(h_cl, 0.0)
        beta_a = self.defense_params.get(a_cl, 0.0)
        alpha_a = self.attack_params.get(a_cl, 0.0)
        beta_h = self.defense_params.get(h_cl, 0.0)

        # Gol attesi: lambda = exp(alpha_h + beta_a + gamma), mu = exp(alpha_a + beta_h)
        lam = math.exp(alpha_h + beta_a + self.home_advantage)
        mu = math.exp(alpha_a + beta_h)

        # Limiti di sicurezza su lambda e mu
        lam = max(0.2, min(5.0, lam))
        mu = max(0.2, min(5.0, mu))

        # Calcolo probabilità Poisson base e applicazione tau correction
        matrix_dc = np.zeros((max_goals, max_goals))
        matrix_poisson = np.zeros((max_goals, max_goals))

        for x in range(max_goals):
            px_raw = poisson.pmf(x, lam)
            for y in range(max_goals):
                py_raw = poisson.pmf(y, mu)
                p_indep = px_raw * py_raw
                matrix_poisson[x, y] = p_indep

                tau = tau_correction(x, y, lam, mu, self.rho)
                matrix_dc[x, y] = p_indep * tau

        # Normalizzazione
        sum_dc = np.sum(matrix_dc)
        if sum_dc > 0:
            matrix_dc /= sum_dc

        sum_p = np.sum(matrix_poisson)
        if sum_p > 0:
            matrix_poisson /= sum_p

        # Calcolo quote mercati Dixon-Coles
        p_home_dc = float(np.sum(np.tril(matrix_dc, -1)))
        p_draw_dc = float(np.sum(np.diag(matrix_dc)))
        p_away_dc = float(np.sum(np.triu(matrix_dc, 1)))

        def get_under(matrix, limit):
            return float(sum(matrix[i, j] for i in range(max_goals) for j in range(max_goals) if i + j < limit))

        u15_dc = get_under(matrix_dc, 1.5)
        u25_dc = get_under(matrix_dc, 2.5)
        u35_dc = get_under(matrix_dc, 3.5)

        # GG / NG
        p_0_away = float(np.sum(matrix_dc[:, 0]))
        p_0_home = float(np.sum(matrix_dc[0, :]))
        p_00 = float(matrix_dc[0, 0])
        ng_dc = p_0_home + p_0_away - p_00
        gg_dc = 1.0 - ng_dc

        # Calcolo mercati Poisson classico per confronto
        p_home_poi = float(np.sum(np.tril(matrix_poisson, -1)))
        p_draw_poi = float(np.sum(np.diag(matrix_poisson)))
        p_away_poi = float(np.sum(np.triu(matrix_poisson, 1)))
        u25_poi = get_under(matrix_poisson, 2.5)

        # Top risultati esatti con confronto
        scores = []
        for x in range(min(5, max_goals)):
            for y in range(min(5, max_goals)):
                scores.append({
                    "score": f"{x}-{y}",
                    "prob_dc": float(matrix_dc[x, y]),
                    "prob_poisson": float(matrix_poisson[x, y]),
                    "delta": float(matrix_dc[x, y] - matrix_poisson[x, y]),
                })
        scores_sorted = sorted(scores, key=lambda s: -s["prob_dc"])

        return {
            "home_team": home_team,
            "away_team": away_team,
            "league_name": self.league_name,
            "lambda": round(lam, 3),
            "mu": round(mu, 3),
            "rho": round(self.rho, 4),
            "home_advantage_exp": round(math.exp(self.home_advantage), 3),
            "matrix_dc": matrix_dc,
            "matrix_poisson": matrix_poisson,
            # Quote Dixon-Coles
            "1": round(p_home_dc, 4),
            "X": round(p_draw_dc, 4),
            "2": round(p_away_dc, 4),
            "u15": round(u15_dc, 4),
            "o15": round(1.0 - u15_dc, 4),
            "u25": round(u25_dc, 4),
            "o25": round(1.0 - u25_dc, 4),
            "u35": round(u35_dc, 4),
            "o35": round(1.0 - u35_dc, 4),
            "gg": round(gg_dc, 4),
            "ng": round(ng_dc, 4),
            # Quote Poisson comparate
            "poisson_1": round(p_home_poi, 4),
            "poisson_X": round(p_draw_poi, 4),
            "poisson_2": round(p_away_poi, 4),
            "poisson_u25": round(u25_poi, 4),
            "top_scores": scores_sorted[:6],
        }

    def get_team_strengths(self) -> pd.DataFrame:
        """Restituisce la tabella dei parametri stimati di attacco e difesa."""
        if not self.is_fitted:
            self.fit()

        rows = []
        for team in self.teams:
            att = self.attack_params.get(team, 0.0)
            defe = self.defense_params.get(team, 0.0)
            rows.append({
                "Squadra": team,
                "Attacco (alpha)": round(math.exp(att), 3),
                "Difesa (beta)": round(math.exp(defe), 3),
                "Log Attacco": round(att, 3),
                "Log Difesa": round(defe, 3),
            })
        df_res = pd.DataFrame(rows)
        if not df_res.empty:
            df_res = df_res.sort_values("Attacco (alpha)", ascending=False).reset_index(drop=True)
            df_res.index = df_res.index + 1
            df_res.index.name = "Rank"
        return df_res


# Caching globale degli engine Dixon-Coles per ciascun campionato
_DIXON_COLES_CACHE: Dict[str, DixonColesEngine] = {}


def get_dixon_coles_engine(league_name: str) -> DixonColesEngine:
    """Restituisce un'istanza cached del motore Dixon-Coles per la lega specificata."""
    if league_name not in _DIXON_COLES_CACHE:
        engine = DixonColesEngine(league_name)
        engine.fit()
        _DIXON_COLES_CACHE[league_name] = engine
    return _DIXON_COLES_CACHE[league_name]


def get_dixon_coles_matrix(home_team: str, away_team: str, league_name: str, max_goals: int = DEFAULT_MAX_GOALS) -> dict:
    """
    Firma pubblica richiesta: restituisce la matrice di probabilità dei punteggi esatti
    e tutti i mercati probabilistici d'esito.
    """
    engine = get_dixon_coles_engine(league_name)
    return engine.predict_match(home_team, away_team, max_goals=max_goals)


def predict_dixon_coles_probs(home_team: str, away_team: str, league_name: str) -> dict:
    """
    Firma pubblica per il calcolo delle probabilità d'esito del modello Dixon-Coles.
    """
    engine = get_dixon_coles_engine(league_name)
    res = engine.predict_match(home_team, away_team)
    return {
        "1": res["1"],
        "X": res["X"],
        "2": res["2"],
        "u25": res["u25"],
        "o25": res["o25"],
        "u35": res["u35"],
        "o35": res["o35"],
        "gg": res["gg"],
        "ng": res["ng"],
        "lambda": res["lambda"],
        "mu": res["mu"],
        "rho": res["rho"],
        "top_scores": res["top_scores"],
    }


def get_dixon_coles_team_strengths(league_name: str) -> pd.DataFrame:
    """Restituisce la tabella con i parametri di forza d'attacco e difesa stimati."""
    engine = get_dixon_coles_engine(league_name)
    return engine.get_team_strengths()
