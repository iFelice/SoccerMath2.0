"""
test_shots_residual.py - Test offline (nessuna rete) delle feature
point-in-time di ``audit/shots_residual_test.py``.

Verifica su un fixture sintetico con valori calcolati a mano:

  1. lo stato e' quello di INIZIO GIORNATA: le partite dello stesso giorno non
     entrano nella propria feature ne' in quella delle altre partite del giorno;
  2. la formula e' esattamente quella di produzione
     (``app._shrunk_ratio`` con ``PRIOR_MATCHES``), rapporto osservato/atteso
     con shrinkage verso la media di lega point-in-time;
  3. una riga con statistiche mancanti non entra nello stato e non sposta le
     feature successive (nessuna imputazione, nessun conteggio silenzioso);
  4. il test di leakage PASSA sull'implementazione corretta (troncamento e
     iniezione di futuro non cambiano nulla);
  5. lo STESSO test CATTURA un leak vero iniettato a mano (statistiche della
     partita stessa): il test ha potere, non e' vacuo.

Uso:  python -m pytest audit/test_shots_residual.py -q
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

import app as prod_app  # noqa: E402
from shots_residual_test import (  # noqa: E402
    SHOT_COLS, build_point_in_time_features, leakage_test,
)

LEAGUE = "Serie A"
TEAMS = ("Alfa", "Beta", "Gamma", "Delta")


def _row(season, day, home, away, hs, as_, hst, ast):
    return {
        "league": LEAGUE, "season": season, "date_day": pd.Timestamp(day),
        "home": home, "away": away, "FTHG": 1, "FTAG": 1,
        "HS": hs, "AS": as_, "HST": hst, "AST": ast,
        "stats_complete": all(v is not None and np.isfinite(v)
                              for v in (hs, as_, hst, ast)),
    }


def hand_fixture() -> pd.DataFrame:
    """3 giornate, 4 squadre, valori scelti per il calcolo a mano."""
    return pd.DataFrame([
        _row("2022/23", "2022-08-13", "Alfa", "Beta", 10, 20, 5, 10),
        _row("2022/23", "2022-08-13", "Gamma", "Delta", 30, 40, 15, 20),
        _row("2022/23", "2022-08-20", "Alfa", "Gamma", 11, 21, 6, 11),
        _row("2022/23", "2022-08-20", "Beta", "Delta", 1, 2, 0, 1),
        _row("2022/23", "2022-08-27", "Alfa", "Delta", 12, 22, 7, 12),
    ])


def long_fixture(days: int = 14) -> pd.DataFrame:
    """Fixture lunga: 2 partite al giorno, ogni squadra gioca ogni giornata."""
    rows = []
    for d in range(1, days + 1):
        day = f"2022-{8 + (d - 1) // 28:02d}-{13 + (d - 1) % 28:02d}"
        pairs = (("Alfa", "Beta"), ("Gamma", "Delta")) if d % 2 else (
            ("Beta", "Alfa"), ("Delta", "Gamma"))
        for i, (home, away) in enumerate(pairs):
            base = 5 + d + i
            rows.append(_row("2022/23", f"2022-09-{d:02d}", home, away,
                             base, base + 3, base // 2, base // 2 + 1))
    return pd.DataFrame(rows)


def test_prima_giornata_senza_storico() -> None:
    """Alla prima giornata nessuna squadra ha visto partite: feature = 0."""
    feat = build_point_in_time_features(hand_fixture())
    first = feat[feat["date_day"] == pd.Timestamp("2022-08-13")]
    assert (first["x_vol_home"] == 0).all() and (first["x_sot_home"] == 0).all()
    assert (first["n_home"] == 0).all() and (first["n_away"] == 0).all()


def test_stato_a_inizio_giornata() -> None:
    """Alfa al 20/08 ha visto UNA partita (il 13/08), non quella del 20/08."""
    feat = build_point_in_time_features(hand_fixture())
    row = feat[(feat["date_day"] == pd.Timestamp("2022-08-20"))
               & (feat["home"] == "Alfa")].iloc[0]
    assert row["n_home"] == 1
    assert row["n_away"] == 1     # Gamma: solo il 13/08


def test_formula_shrinkage_di_produzione() -> None:
    """x_vol del 27/08 e' ricalcolabile a mano con ``app._shrunk_ratio``."""
    feat = build_point_in_time_features(hand_fixture())
    row = feat[(feat["date_day"] == pd.Timestamp("2022-08-27"))
               & (feat["home"] == "Alfa")].iloc[0]
    # Stato a inizio 27/08 (4 partite viste, 8 squadra-partite):
    #   tiri totali = 10+20+30+40+11+21+1+2 = 135 -> media lega = 135/8
    #   Alfa: 2 partite, tiri fatti 10+11 = 21, concessi 20+21 = 41
    #   Delta: 2 partite, tiri concessi 30+1 = 31
    mean_shots = 135 / 8
    r_att = prod_app._shrunk_ratio(21 / 2, mean_shots, 2)
    r_def = prod_app._shrunk_ratio(31 / 2, mean_shots, 2)
    assert np.isclose(row["x_vol_home"], np.log(r_att) + np.log(r_def),
                      atol=1e-12)
    # valore atteso indipendente dalla produzione (calcolo a mano)
    assert np.isclose(r_att, (2 * (10.5 / 16.875) + 6) / 8, atol=1e-12)
    assert np.isclose(row["x_vol_home"], np.log((2 * (10.5 / 16.875) + 6) / 8)
                      + np.log((2 * (15.5 / 16.875) + 6) / 8), atol=1e-12)


def test_lega_inversa_simmetrica() -> None:
    """x_vol_away usa i tiri fatti della trasferta e i concessi della casa."""
    feat = build_point_in_time_features(hand_fixture())
    row = feat[(feat["date_day"] == pd.Timestamp("2022-08-27"))
               & (feat["home"] == "Alfa")].iloc[0]
    mean_shots = 135 / 8
    r_att_away = prod_app._shrunk_ratio(42 / 2, mean_shots, 2)     # Delta fatti
    r_def_home = prod_app._shrunk_ratio(41 / 2, mean_shots, 2)     # Alfa concessi
    assert np.isclose(row["x_vol_away"], np.log(r_att_away) + np.log(r_def_home),
                      atol=1e-12)
    # simmetria: scambiare casa e trasferta scambia x_vol_home e x_vol_away
    swapped = hand_fixture()
    last = swapped.index[-1]
    swapped.loc[last, ["home", "away"]] = ["Delta", "Alfa"]
    swapped.loc[last, ["HS", "AS"]] = [22, 12]
    swapped.loc[last, ["HST", "AST"]] = [12, 7]
    feat2 = build_point_in_time_features(swapped)
    row2 = feat2[feat2["date_day"] == pd.Timestamp("2022-08-27")].iloc[0]
    assert np.isclose(row2["x_vol_home"], row["x_vol_away"], atol=1e-12)
    assert np.isclose(row2["x_vol_away"], row["x_vol_home"], atol=1e-12)


def test_riga_incompleta_non_entra_nello_stato() -> None:
    """Una riga senza tiri e' identica a una riga assente (nessuna imputazione)."""
    base = hand_fixture()
    incomplete = base.copy()
    i = incomplete.index[3]      # Beta-Delta del 20/08
    for col in SHOT_COLS:
        incomplete.loc[i, col] = np.nan
    incomplete.loc[i, "stats_complete"] = False
    still = build_point_in_time_features(incomplete)
    absent = build_point_in_time_features(base.drop(index=i).reset_index(drop=True))
    key = ["date_day", "home", "away"]
    cols = ["x_vol_home", "x_sot_home", "x_vol_away", "x_sot_away",
            "n_home", "n_away"]
    left = still[still["date_day"] == pd.Timestamp("2022-08-27")][key + cols]
    right = absent[absent["date_day"] == pd.Timestamp("2022-08-27")][key + cols]
    pd.testing.assert_frame_equal(left.reset_index(drop=True),
                                  right.reset_index(drop=True))


def test_leakage_futuro_non_cambia_niente() -> None:
    """Troncamento e iniezione di futuro: nessuna differenza (test superato)."""
    src = long_fixture()
    src["fk"] = (src["league"].astype(str) + "|" + src["date_day"].astype(str)
                 + "|" + src["home"] + "|" + src["away"])
    result = leakage_test(src, sample_per_league=3, seed=7)
    assert result["matches_tested"] == 3
    assert result["variants_a_b"]["max_abs_difference"] == 0.0
    assert result["variants_a_b"]["difference_count"] == 0
    assert result["variants_a_b"]["esito"] == "OK"


def test_leakage_rileva_un_leak_vero() -> None:
    """Iniezione delle statistiche della partita stessa: il test DEVE rilevarla."""
    src = long_fixture()
    src["fk"] = (src["league"].astype(str) + "|" + src["date_day"].astype(str)
                 + "|" + src["home"] + "|" + src["away"])
    result = leakage_test(src, sample_per_league=3, seed=7)
    leak = result["variant_c_true_leak"]
    assert leak["max_abs_difference"] > 0
    assert leak["matches_with_leak_detected"] == 3
    assert leak["esito"].startswith("OK")


def test_scope_stagionale_azzera_a_inizio_stagione() -> None:
    """Con scope='season' la seconda stagione riparte da zero."""
    first = long_fixture()
    second = long_fixture()
    second["season"] = "2023/24"
    second["date_day"] = (second["date_day"]
                          + pd.Timedelta(days=365)).dt.normalize()
    src = pd.concat([first, second], ignore_index=True)
    feat = build_point_in_time_features(src, scope="season")
    start = feat[(feat["season"] == "2023/24")
                 & (feat["date_day"] == second["date_day"].min())]
    assert (start["n_home"] == 0).all()
    cumulative = build_point_in_time_features(src, scope="cumulative")
    start_cum = cumulative[(cumulative["season"] == "2023/24")
                           & (cumulative["date_day"]
                              == second["date_day"].min())]
    assert (start_cum["n_home"] > 0).all()


if __name__ == "__main__":                    # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
