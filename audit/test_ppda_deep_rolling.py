"""
test_ppda_deep_rolling.py - Test offline (nessuna rete) dell'archivio
point-in-time costruito da ``audit/build_ppda_deep_rolling.py``.

Verifica su un fixture sintetico, con valori calcolati a mano:

  1. la media mobile usa SOLO partite con kickoff strettamente precedente;
  2. sotto ``MIN_MATCHES`` partite precedenti le feature sono NaN (nessuna
     statistica inventata), fra ``MIN_MATCHES`` e N-1 la media e' sulle n
     partite disponibili con ``status="partial"``;
  3. un PPDA non calcolabile (``None``) non entra nella media e non vale 0;
  4. una partita dello stesso giorno SENZA orario resta fuori dalla finestra
     (regola conservativa di ``xg_archive.parse_kickoff``);
  5. il test di leakage passa sull'implementazione corretta;
  6. lo STESSO test cattura un'implementazione che guarda avanti: il test ha
     potere, non e' vacuo.

Uso:  python -m pytest audit/test_ppda_deep_rolling.py -q
"""
from __future__ import annotations

import json
import os
import sys

import pytest

_AUDIT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_AUDIT_DIR)
sys.path.insert(0, _AUDIT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "SoccerMath"))

import build_ppda_deep_rolling as builder  # noqa: E402

LEAGUE = "Serie A"


def _write_fixture(db_dir: str) -> None:
    """8 partite dell'Inter con valori noti, 3 del Milan (un PPDA nullo) e 2
    Juventus/Milan (una SENZA orario)."""
    records = []
    for i in range(8):
        records.append({
            "season": 2022, "id": 100 + i,
            "date": f"2022-08-{13 + i:02d} 18:45:00",
            "home_team": "Inter", "away_team": "Torino", "is_result": True,
            "home_ppda": 10.0 + i, "away_ppda": 20.0 + i,
            "home_deep_completions": i, "away_deep_completions": 2 * i,
        })
    records.append({
        "season": 2022, "id": 200, "date": "2022-09-01",
        "home_team": "Juventus", "away_team": "Milan", "is_result": True,
        "home_ppda": 12.0, "away_ppda": 13.0,
        "home_deep_completions": 4, "away_deep_completions": 6,
    })
    for i, ppda in enumerate((11.0, None, 13.0)):
        records.append({
            "season": 2022, "id": 150 + i,
            "date": f"2022-08-{20 + i:02d} 20:45:00",
            "home_team": "Milan", "away_team": "Juventus", "is_result": True,
            "home_ppda": ppda, "away_ppda": 15.0,
            "home_deep_completions": 3 + i, "away_deep_completions": 1,
        })
    records.append({
        "season": 2022, "id": 201, "date": "2022-09-01 20:45:00",
        "home_team": "Milan", "away_team": "Juventus", "is_result": True,
        "home_ppda": None, "away_ppda": 14.0,
        "home_deep_completions": 5, "away_deep_completions": 7,
    })
    os.makedirs(db_dir, exist_ok=True)
    with open(os.path.join(db_dir, "ppda_deep_serie_a.json"), "w",
              encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False)


@pytest.fixture()
def rows(tmp_path):
    _write_fixture(str(tmp_path))
    problems = []
    matches = builder.load_matches(LEAGUE, str(tmp_path), problems=problems)
    assert problems == []
    assert len(matches) == 13
    return {row["id"]: row
            for row in builder.build_league(LEAGUE, matches)}, str(tmp_path)


def test_media_mobile_solo_passato(rows):
    """Partita 104: prima di lei l'Inter ha giocato 100-103.

    own_ppda 10,11,12,13 -> 11.5; own_deep 0,1,2,3 -> 1.5;
    faced_ppda 20,21,22,23 -> 21.5; faced_deep 0,2,4,6 -> 3.0.
    Il valore della partita stessa (home_ppda=14) NON entra.
    """
    data, _ = rows
    row = data[104]
    assert row["home_r5_own_ppda"] == pytest.approx(11.5)
    assert row["home_r5_own_deep"] == pytest.approx(1.5)
    assert row["home_r5_faced_ppda"] == pytest.approx(21.5)
    assert row["home_r5_faced_deep"] == pytest.approx(3.0)
    assert row["home_r10_own_ppda"] == pytest.approx(11.5)
    assert row["home_r5_n"] == 4
    assert row["home_r5_status"] == "partial"
    assert row["home_r10_status"] == "partial"
    assert row["home_r5_own_ppda"] != 14.0


def test_finestre_non_piene_nessuna_statistica_inventata(rows):
    data, _ = rows
    assert data[100]["home_r5_status"] == "insufficient"
    assert data[100]["home_r5_own_ppda"] is None
    assert data[100]["home_r10_own_ppda"] is None
    # n=2 < MIN_MATCHES -> NaN anche se i valori esisterebbero
    assert data[102]["home_r5_n"] == 2
    assert data[102]["home_r5_status"] == "insufficient"
    assert data[102]["home_r5_own_ppda"] is None
    # n=3 == MIN_MATCHES -> media sulle 3 partite, finestra dichiarata partial
    assert data[103]["home_r5_n"] == 3
    assert data[103]["home_r5_status"] == "partial"
    assert data[103]["home_r5_own_ppda"] == pytest.approx(11.0)
    # finestra piena
    assert data[107]["home_r5_n"] == 5
    assert data[107]["home_r5_status"] == "full"
    assert data[107]["home_r5_own_ppda"] == pytest.approx(14.0)
    # finestra 102-106: la piu' vecchia e' il 2022-08-15, la partita e' il 20
    assert data[107]["home_r5_age_days"] == pytest.approx(5.0)


def test_ppda_non_calcolabile_escluso_e_giorno_senza_orario_escluso(rows):
    """Milan in 201 (2022-09-01 20:45).

    Partite precedenti: 150,151,152 in casa e 200 in trasferta. La 200 e'
    SENZA orario e cade lo stesso giorno: l'ordine dentro il giorno non e'
    conoscibile, quindi resta fuori. In finestra own_ppda validi = 11.0, 13.0
    (il ``None`` e' escluso, non contato come 0) -> 12.0 su n_ppda=2;
    own_deep = 3,4,5 -> 4.0; faced_ppda = 15.0.
    """
    data, _ = rows
    row = data[201]
    assert row["home_r5_n"] == 3
    assert row["home_r5_n_own_ppda"] == 2
    assert row["home_r5_own_ppda"] == pytest.approx(12.0)
    assert row["home_r5_own_deep"] == pytest.approx(4.0)
    assert row["home_r5_faced_ppda"] == pytest.approx(15.0)


def test_leakage_assente_su_implementazione_corretta(rows):
    _, db_dir = rows
    result = builder.leakage_test(db_dir, [LEAGUE], sample_per_league=4,
                                  seed=7, windows=(5,))
    # 105, 106, 107: le uniche tre con almeno 5 partite precedenti
    assert result["matches_tested"] == 3, result["per_league"]
    assert result["injected_future_matches"] > 0
    assert result["difference_count"] == 0, result["differences"]
    assert result["max_abs_difference"] == 0.0


def test_leakage_test_ha_potere(rows):
    """Lo stesso test, su un'implementazione che include la partita stessa."""
    _, db_dir = rows
    original = builder.rolling_values

    def leaky(entries, index, window):
        padded = list(entries)
        if index + 1 < len(padded):
            return original(padded, index + 1, window)
        return original(entries, index, window)

    builder.rolling_values = leaky
    try:
        bad = builder.leakage_test(db_dir, [LEAGUE], sample_per_league=4,
                                   seed=7, windows=(5,))
    finally:
        builder.rolling_values = original
    assert bad["difference_count"] > 0, "il test non ha catturato il leakage"


def test_csv_scrive_e_rilegge_le_stesse_colonne(rows, tmp_path):
    _, db_dir = rows
    matches = builder.load_matches(LEAGUE, db_dir)
    built = builder.build_league(LEAGUE, matches)
    out = os.path.join(str(tmp_path), "out", "rolling.csv")
    assert builder.write_csv(built, out) == len(built)
    with open(out, encoding="utf-8") as f:
        header = f.readline().strip().split(",")
    for column in ("home_r5_own_ppda", "away_r10_faced_deep",
                   "home_r5_status", "away_r10_age_days"):
        assert column in header
