import pandas as pd
import numpy as np
import math
import time
from config import LEAGUES_CONFIG, get_league_db_files, clean_name, LEAGUE_HOME_ADVANTAGE
from models.dixon_coles import DixonColesEngine
from scipy.stats import poisson

def evaluate_all_leagues_fast():
    print("==========================================================================")
    print(" ANALISI SCIENTIFICA DELLA LOGICA DEI PRONOSTICI SU DATI STORICI")
    print("==========================================================================")
    
    summary_data = []
    
    for league_name in LEAGUES_CONFIG.keys():
        files = get_league_db_files(league_name)
        dfs = []
        for f in files:
            try:
                df_tmp = pd.read_csv(f, on_bad_lines="warn", low_memory=False)
                needed = {"HomeTeam", "AwayTeam", "FTR", "Date", "FTHG", "FTAG"}
                if not df_tmp.empty and needed.issubset(df_tmp.columns):
                    dfs.append(df_tmp[["Date", "HomeTeam", "AwayTeam", "FTR", "FTHG", "FTAG"]].copy())
            except Exception:
                continue
        if not dfs:
            print(f"[-] Nessun dato per {league_name}")
            continue
        
        df = pd.concat(dfs, ignore_index=True)
        df["HomeClean"] = df["HomeTeam"].apply(clean_name)
        df["AwayClean"] = df["AwayTeam"].apply(clean_name)
        df["Date_Parsed"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
        df["FTHG"] = pd.to_numeric(df["FTHG"], errors="coerce")
        df["FTAG"] = pd.to_numeric(df["FTAG"], errors="coerce")
        df = df.dropna(subset=["Date_Parsed", "FTHG", "FTAG", "FTR", "HomeClean", "AwayClean"])
        df = df[(df["HomeClean"] != "") & (df["AwayClean"] != "")]
        df = df.drop_duplicates(subset=["Date_Parsed", "HomeClean", "AwayClean"], keep="last").sort_values("Date_Parsed").reset_index(drop=True)
        
        n_total = len(df)
        if n_total < 50:
            continue
            
        test_size = min(200, n_total - 50)
        test_start = n_total - test_size
        
        pois_correct = 0
        elo_correct = 0
        dc_correct = 0
        ens_correct = 0
        
        uo_correct = 0
        gg_correct = 0
        
        brier_pois, brier_elo, brier_dc, brier_ens = [], [], [], []
        logloss_pois, logloss_elo, logloss_dc, logloss_ens = [], [], [], []
        
        home_adv = LEAGUE_HOME_ADVANTAGE.get(league_name, 60.0)
        elo_ratings = {}
        
        # Warmup Elo on training set
        for idx in range(test_start):
            row = df.iloc[idx]
            h, a, ftr = row["HomeClean"], row["AwayClean"], str(row["FTR"]).strip().upper()
            r_h = elo_ratings.get(h, 1500.0)
            r_a = elo_ratings.get(a, 1500.0)
            dr = r_h + home_adv - r_a
            e_h = 1.0 / (1.0 + 10.0 ** (-dr / 400.0))
            s_h = 1.0 if ftr == "H" else (0.0 if ftr == "A" else 0.5)
            k = 24.0
            elo_ratings[h] = r_h + k * (s_h - e_h)
            elo_ratings[a] = r_a + k * ((1.0 - s_h) - (1.0 - e_h))
            
        # Fit analytical Dixon-Coles on training set
        dc_engine = DixonColesEngine(league_name)
        train_df = df.iloc[:test_start].copy()
        dc_engine.teams = sorted(list(set(train_df["HomeClean"]).union(set(train_df["AwayClean"]))))
        dc_engine.team_idx = {t: i for i, t in enumerate(dc_engine.teams)}
        dc_engine._analytical_fallback(train_df)
        
        eval_count = 0
        
        for idx in range(test_start, n_total):
            row = df.iloc[idx]
            h, a = row["HomeClean"], row["AwayClean"]
            fthg, ftag = int(row["FTHG"]), int(row["FTAG"])
            ftr = str(row["FTR"]).strip().upper()
            real_1x2 = "1" if ftr == "H" else ("2" if ftr == "A" else "X")
            real_y = np.array([1.0 if real_1x2=="1" else 0.0, 1.0 if real_1x2=="X" else 0.0, 1.0 if real_1x2=="2" else 0.0])
            
            # --- 1. Poisson model ---
            sub_train = df.iloc[:idx]
            avg_h = max(sub_train["FTHG"].mean(), 0.1)
            avg_a = max(sub_train["FTAG"].mean(), 0.1)
            
            h_matches = sub_train[(sub_train["HomeClean"] == h) | (sub_train["AwayClean"] == h)]
            a_matches = sub_train[(sub_train["HomeClean"] == a) | (sub_train["AwayClean"] == a)]
            
            att_h = (h_matches["FTHG"].where(h_matches["HomeClean"] == h, h_matches["FTAG"]).sum() / max(1, len(h_matches))) / ((avg_h + avg_a) / 2)
            def_h = (h_matches["FTAG"].where(h_matches["HomeClean"] == h, h_matches["FTHG"]).sum() / max(1, len(h_matches))) / ((avg_h + avg_a) / 2)
            
            att_a = (a_matches["FTHG"].where(a_matches["HomeClean"] == a, a_matches["FTAG"]).sum() / max(1, len(a_matches))) / ((avg_h + avg_a) / 2)
            def_a = (a_matches["FTAG"].where(a_matches["HomeClean"] == a, a_matches["FTHG"]).sum() / max(1, len(a_matches))) / ((avg_h + avg_a) / 2)
            
            lam = max(0.2, att_h * def_a * avg_h)
            mu = max(0.2, att_a * def_h * avg_a)
            
            max_g = 10
            p_mat = np.zeros((max_g, max_g))
            for x in range(max_g):
                px = poisson.pmf(x, lam)
                for y in range(max_g):
                    p_mat[x, y] = px * poisson.pmf(y, mu)
            p_mat /= np.sum(p_mat)
            
            p1_p = float(np.sum(np.tril(p_mat, -1)))
            px_p = float(np.sum(np.diag(p_mat)))
            p2_p = float(np.sum(np.triu(p_mat, 1)))
            p_vec = np.array([p1_p, px_p, p2_p])
            pred_p = ["1", "X", "2"][np.argmax(p_vec)]
            
            # --- 2. Elo Model ---
            r_h = elo_ratings.get(h, 1500.0)
            r_a = elo_ratings.get(a, 1500.0)
            dr = r_h + home_adv - r_a
            e_h = 1.0 / (1.0 + 10.0 ** (-dr / 400.0))
            p_draw = max(0.06, min(0.34, 0.27 * math.exp(-((dr / 320.0) ** 2))))
            p1_e = (1.0 - p_draw) * e_h
            p2_e = (1.0 - p_draw) * (1.0 - e_h)
            tot_e = p1_e + p_draw + p2_e
            e_vec = np.array([p1_e/tot_e, p_draw/tot_e, p2_e/tot_e])
            pred_e = ["1", "X", "2"][np.argmax(e_vec)]
            
            # --- 3. Dixon Coles ---
            dc_res = dc_engine.predict_match(h, a)
            dc_vec = np.array([dc_res["1"], dc_res["X"], dc_res["2"]])
            pred_dc = ["1", "X", "2"][np.argmax(dc_vec)]
            
            # --- 4. Ensemble ---
            ens_vec = 0.6 * p_vec + 0.4 * e_vec
            pred_ens = ["1", "X", "2"][np.argmax(ens_vec)]
            
            if pred_p == real_1x2: pois_correct += 1
            if pred_e == real_1x2: elo_correct += 1
            if pred_dc == real_1x2: dc_correct += 1
            if pred_ens == real_1x2: ens_correct += 1
            
            uo_real = "OVER" if (fthg + ftag) > 2.5 else "UNDER"
            uo_pred = "OVER" if (1.0 - dc_res["u25"]) > 0.5 else "UNDER"
            if uo_pred == uo_real: uo_correct += 1
            
            gg_real = "GG" if (fthg > 0 and ftag > 0) else "NG"
            gg_pred = "GG" if dc_res["gg"] > 0.5 else "NG"
            if gg_pred == gg_real: gg_correct += 1
            
            brier_pois.append(np.sum((real_y - p_vec)**2))
            brier_elo.append(np.sum((real_y - e_vec)**2))
            brier_dc.append(np.sum((real_y - dc_vec)**2))
            brier_ens.append(np.sum((real_y - ens_vec)**2))
            
            logloss_pois.append(-np.sum(real_y * np.log(np.clip(p_vec, 1e-15, 1-1e-15))))
            logloss_elo.append(-np.sum(real_y * np.log(np.clip(e_vec, 1e-15, 1-1e-15))))
            logloss_dc.append(-np.sum(real_y * np.log(np.clip(dc_vec, 1e-15, 1-1e-15))))
            logloss_ens.append(-np.sum(real_y * np.log(np.clip(ens_vec, 1e-15, 1-1e-15))))
            
            # Update Elo
            s_h = 1.0 if ftr == "H" else (0.0 if ftr == "A" else 0.5)
            elo_ratings[h] = r_h + 24.0 * (s_h - e_h)
            elo_ratings[a] = r_a + 24.0 * ((1.0 - s_h) - (1.0 - e_h))
            
            eval_count += 1
            
        acc_p = pois_correct / eval_count * 100
        acc_e = elo_correct / eval_count * 100
        acc_dc = dc_correct / eval_count * 100
        acc_ens = ens_correct / eval_count * 100
        acc_uo = uo_correct / eval_count * 100
        acc_gg = gg_correct / eval_count * 100
        
        summary_data.append({
            "League": league_name,
            "Matches": eval_count,
            "Pois_1X2_%": round(acc_p, 2),
            "Elo_1X2_%": round(acc_e, 2),
            "DC_1X2_%": round(acc_dc, 2),
            "Ens_1X2_%": round(acc_ens, 2),
            "UO_2.5_%": round(acc_uo, 2),
            "GG_NG_%": round(acc_gg, 2),
            "Brier_Ens": round(np.mean(brier_ens), 4),
            "LogLoss_Ens": round(np.mean(logloss_ens), 4)
        })
        
    df_sum = pd.DataFrame(summary_data)
    print("\n" + df_sum.to_string(index=False))

if __name__ == "__main__":
    evaluate_all_leagues_fast()
