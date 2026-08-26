import numpy as np
import pandas as pd


def calculate_brier_score(y_true, y_prob):
    """Calcola il Brier Score tra i risultati reali (one-hot) e le probabilità predette."""
    return np.mean(np.sum((y_true - y_prob) ** 2, axis=1))


def calculate_log_loss(y_true, y_prob, eps=1e-15):
    """Calcola la Log-Loss multiclasse clipped per stabilità numerica."""
    y_prob = np.clip(y_prob, eps, 1 - eps)
    return -np.mean(np.sum(y_true * np.log(y_prob), axis=1))


def run_backtest(df, initial_bankroll=1000.0, stake_type="flat", stake_amount=10.0):
    """Esegue il backtest sulle scommesse e calcola l'evoluzione della bankroll."""
    if df.empty:
        return {"error": "DataFrame vuoto"}

    bankroll = initial_bankroll
    history = [bankroll]
    total_bets = 0
    wins = 0

    for idx, row in df.iterrows():
        if row.get("value_bet", False):
            total_bets += 1
            stake = (
                stake_amount
                if stake_type == "flat"
                else row.get("kelly_stake", stake_amount)
            )

            if row.get("result") == row.get("predicted_result"):
                profit = stake * (row.get("odd", 1.0) - 1)
                bankroll += profit
                wins += 1
            else:
                bankroll -= stake

            history.append(bankroll)

    roi = (
        ((bankroll - initial_bankroll) / (total_bets * stake_amount)) * 100
        if total_bets > 0
        else 0.0
    )
    win_rate = (wins / total_bets) * 100 if total_bets > 0 else 0.0

    return {
        "final_bankroll": round(bankroll, 2),
        "total_bets": total_bets,
        "win_rate": round(win_rate, 2),
        "roi_percent": round(roi, 2),
        "bankroll_history": history,
    }


def compare_models_backtest(df, models_list=None, initial_bankroll=1000.0, stake_amount=10.0):
    """Confronta le prestazioni di diversi modelli e restituisce un DataFrame."""
    if df.empty:
        return pd.DataFrame()

    if models_list is None:
        models_list = ["Poisson", "Dixon-Coles", "Ensemble"]

    results = []
    for model_name in models_list:
        res = run_backtest(df, initial_bankroll=initial_bankroll, stake_amount=stake_amount)
        results.append({
            "Modello": model_name,
            "Bankroll Finale (€)": res.get("final_bankroll", initial_bankroll),
            "Scommesse Totali": res.get("total_bets", 0),
            "Win Rate (%)": res.get("win_rate", 0.0),
            "ROI (%)": res.get("roi_percent", 0.0)
        })

    return pd.DataFrame(results)


def detect_value_bets(df, min_ev=0.02):
    """Individua le scommesse a valore (EV >= min_ev)."""
    if df.empty:
        return pd.DataFrame()

    if "ev" in df.columns:
        return df[df["ev"] >= min_ev].copy()

    return df.copy()