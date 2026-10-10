"""Test di audit per il fit della griglia su una LINEA TOTALS QUALUNQUE.

Copre il punto 4 dell'audit (estensione di ``audit/griglia_core.py``): linee a
meta' (1,5 / 2,5 / 3,5), linee intere (2 / 3) con rimborso sul pareggio di linea
e linee a quarti (2,25 / 2,75) con mezza puntata su ciascuna delle due linee
adiacenti, quota equa dalla condizione di valore atteso nullo.

Nessuna rete, nessuna chiave, nessuna dipendenza da SoccerMath/: solo la
matematica di ``griglia_core``. I test sono di "andata e ritorno": si genera una
griglia da parametri noti, si calcola il bersaglio sulla linea e si rifitta la
griglia, chiedendo il residuo al livello di macchina.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import griglia_core as gc  # noqa: E402


# ---------------------------------------------------------------------------
# 1. Probabilita' giusta della linea, per tipo
# ---------------------------------------------------------------------------
def totali(m):
    """Distribuzione dei gol totali dalla griglia (indice = gol totali)."""
    return np.array([np.trace(m, offset=k) for k in range(-gc.K, gc.K + 1)][::-1]) \
        if False else _totali_esplicita(m)


def _totali_esplicita(m):
    n = gc.N
    tot = np.zeros(2 * n - 1)
    for i in range(n):
        for j in range(n):
            tot[i + j] += m[i, j]
    return tot


def test_linea_mezza_probabilita_diretta():
    m = gc.dc_matrix(1.6, 1.1, -0.07)
    tot = _totali_esplicita(m)
    for line in (1.5, 2.5, 3.5):
        p = gc.grid_line_prob(m, line, "over")
        attesa = float(tot[int(line + 0.5):].sum())
        assert abs(p - attesa) < 1e-14, (line, p, attesa)
        # nessun rimborso su una linea a meta'
        _W, _Lp, Pp = gc.grid_line_parts(m, line, "over")
        assert abs(Pp) < 1e-14


def test_linea_intera_rimborso_sul_pareggio_di_linea():
    m = gc.dc_matrix(1.4, 1.3, -0.05)
    tot = _totali_esplicita(m)
    for line in (2.0, 3.0):
        W, Lp, Pp = gc.grid_line_parts(m, line, "over")
        k = int(line)
        assert abs(W - tot[k + 1:].sum()) < 1e-14
        assert abs(Lp - tot[:k].sum()) < 1e-14
        assert abs(Pp - tot[k]) < 1e-14, "sulla linea intera la puntata e' rimborsata"
        p = gc.grid_line_prob(m, line, "over")
        attesa = float(tot[k + 1:].sum() / (1.0 - tot[k]))
        assert abs(p - attesa) < 1e-14, (line, p, attesa)


def test_linea_a_quarti_e_media_delle_due_linee_adiacenti():
    m = gc.dc_matrix(1.5, 1.2, -0.09)
    tot = _totali_esplicita(m)
    # 2,25 = ½ Over 2,0 + ½ Over 2,5: vince sui gol >= 3, perde interamente sotto 2
    # e perde META' (= -0,5 puntate) sui 2 gol esatti.
    W, Lp, _Pp = gc.grid_line_parts(m, 2.25, "over")
    assert abs(W - tot[3:].sum()) < 1e-14
    assert abs(Lp - (tot[:2].sum() + 0.5 * tot[2])) < 1e-14
    # 2,75 = ½ Over 2,5 + ½ Over 3,0: vince interamente da 4 gol, vince META' a 3 gol
    W, Lp, _Pp = gc.grid_line_parts(m, 2.75, "over")
    assert abs(W - (tot[4:].sum() + 0.5 * tot[3])) < 1e-14
    assert abs(Lp - tot[:3].sum()) < 1e-14


def test_over_e_under_sommano_a_uno_per_ogni_tipo_di_linea():
    m = gc.dc_matrix(1.1, 1.9, 0.03)
    for line in (1.5, 2.0, 2.25, 2.5, 2.75, 3.0, 3.5, 3.25, 4.75):
        po = gc.grid_line_prob(m, line, "over")
        pu = gc.grid_line_prob(m, line, "under")
        assert abs(po + pu - 1.0) < 1e-14, (line, po, pu)


def test_quota_equa_annulla_l_aspettativa_secondo_le_regole_di_pagamento():
    """EV = 0 con la quota equa, usando le regole di pagamento SCRITTE A MANO.

    Le tabelle di profitto sono ricostruite qui dalla definizione del mercato
    (non dai pesi di griglia_core): se i pesi fossero sbagliati l'EV non
    tornerebbe a zero.
    """
    m = gc.dc_matrix(1.7, 1.0, -0.06)
    tot = _totali_esplicita(m)
    t = np.arange(len(tot))

    def profitto(line, o):
        if line == 2.25:                       # ½ su Over 2,0 e ½ su Over 2,5
            return np.where(t >= 3, (o - 1.0), np.where(t == 2, -0.5, -1.0))
        if line == 2.75:                       # ½ su Over 2,5 e ½ su Over 3,0
            return np.where(t >= 4, (o - 1.0), np.where(t == 3, 0.5 * (o - 1.0), -1.0))
        if line == 3.25:                       # ½ su Over 3,0 e ½ su Over 3,5
            return np.where(t >= 4, (o - 1.0), np.where(t == 3, -0.5, -1.0))
        raise AssertionError(line)

    for line in (2.25, 2.75, 3.25):
        o = gc.grid_line_fair_odds(m, line, "over")
        ev = float(np.sum(tot * profitto(line, o)))
        assert abs(ev) < 1e-13, (line, o, ev)
        # la quota equa e' anche 1 / p_equa
        assert abs(o - 1.0 / gc.grid_line_prob(m, line, "over")) < 1e-12


def test_linee_non_ammesse_e_lato_errato():
    m = gc.dc_matrix(1.2, 1.2, 0.0)
    with pytest.raises(ValueError):
        gc.grid_line_prob(m, 2.3, "over")     # non un multiplo di 0,25
    with pytest.raises(ValueError):
        gc.grid_line_prob(m, 0.0, "over")     # linea nulla
    with pytest.raises(ValueError):
        gc.grid_line_prob(m, 2.5, "laterale")


# ---------------------------------------------------------------------------
# 2. Andata e ritorno del fit su parametri noti
# ---------------------------------------------------------------------------
LINEE = [1.5, 2.0, 2.25, 2.5, 2.75, 3.0, 3.5, 4.25]
PARAMETRI = [(1.6, 1.1, -0.08), (0.9, 1.7, -0.04), (1.3, 1.3, 0.05), (2.0, 0.7, -0.12)]


@pytest.mark.parametrize("line", LINEE)
@pytest.mark.parametrize("side", ["over", "under"])
@pytest.mark.parametrize("lam,mu,rho", PARAMETRI)
def test_fit_generalizzato_recupera_i_parametri(line, side, lam, mu, rho):
    m = gc.dc_matrix(lam, mu, rho)
    v = gc.grid_1x2_line(m, line, side)
    f = gc.fit_implicit_line(v[0], v[1], v[2], v[3], line=line, side=side, rho_free=True)
    assert f["max_abs_resid"] < 1e-9, (line, side, lam, mu, rho, f["max_abs_resid"])
    assert f["lam"] == pytest.approx(lam, abs=1e-6)
    assert f["mu"] == pytest.approx(mu, abs=1e-6)
    assert f["rho"] == pytest.approx(rho, abs=1e-6)
    # la griglia rifittata riproduce la linea e la terna
    m2 = gc.dc_matrix(f["lam"], f["mu"], f["rho"])
    v2 = gc.grid_1x2_line(m2, line, side)
    np.testing.assert_allclose(v2, v, atol=1e-9)


@pytest.mark.parametrize("line", LINEE)
def test_fit_generalizzato_rho_zero(line):
    lam, mu = 1.45, 1.05
    m = gc.dc_matrix(lam, mu, 0.0)
    v = gc.grid_1x2_line(m, line, "over")
    f = gc.fit_implicit_line(v[0], v[1], v[2], v[3], line=line, side="over", rho_free=False)
    assert f["max_abs_resid"] < 1e-9
    assert f["lam"] == pytest.approx(lam, abs=1e-6)
    assert f["mu"] == pytest.approx(mu, abs=1e-6)
    assert f["rho"] == 0.0


def test_fit_generalizzato_a_2_5_coincide_col_fit_originale():
    """A 2,5 la generalizzazione deve ridarsi esattamente ``fit_implicit``."""
    rng = np.random.default_rng(20261010)
    for _ in range(40):
        lam, mu, rho = rng.uniform(0.6, 2.4, 2).tolist() + [float(rng.uniform(-0.4, 0.2))]
        m = gc.dc_matrix(lam, mu, rho)
        v = gc.grid_1x2_ou(m)
        a = gc.fit_implicit(v[0], v[1], v[2], v[3], rho_free=True)
        b = gc.fit_implicit_line(v[0], v[1], v[2], v[3], line=2.5, side="over", rho_free=True)
        assert abs(a["lam"] - b["lam"]) < 1e-7
        assert abs(a["mu"] - b["mu"]) < 1e-7
        assert abs(a["rho"] - b["rho"]) < 1e-7
        assert b["max_abs_resid"] < 1e-9


def test_devig_somma_uno_e_monotono_sulla_linea():
    """p_equa(Over) decresce al crescere della linea (stessa griglia)."""
    m = gc.dc_matrix(1.5, 1.2, -0.05)
    ps = [gc.grid_line_prob(m, l, "over") for l in (1.5, 2.0, 2.25, 2.5, 2.75, 3.0, 3.5)]
    assert all(a > b for a, b in zip(ps, ps[1:])), ps


# ---------------------------------------------------------------------------
# 3. De-vig: griglia_core e griglia_varianti devono dare gli stessi numeri
# ---------------------------------------------------------------------------
def test_devig_coerente_con_griglia_varianti():
    import griglia_varianti as gv  # noqa: E402  (script della PR #59, sola lettura)
    rng = np.random.default_rng(20261011)
    for _ in range(50):
        odds = rng.uniform(1.05, 12.0, 3)
        if (1.0 / odds).sum() <= 1.0:
            continue
        # nome nel dizionario DEVIG -> nome della funzione in griglia_varianti
        nomi_gv = {"proporzionale": "devig_prop", "Shin": "devig_shin", "potenza": "devig_power"}
        for nome, fn in gc.DEVIG.items():
            np.testing.assert_allclose(fn(odds), getattr(gv, nomi_gv[nome])(odds), atol=1e-12)
    # caso degenere (nessun margine): tutti e tre coincidono col proporzionale
    odds = np.array([2.0, 4.0, 4.0])
    for nome, fn in gc.DEVIG.items():
        np.testing.assert_allclose(fn(odds), gc.devig_prop(odds), atol=1e-12)
