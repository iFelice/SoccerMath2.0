"""Test di audit per griglia_varianti.py (sola lettura, nessuna rete)."""

import os
import sys

import numpy as np
import pytest

_AUDIT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _AUDIT)

import griglia_varianti as gv  # noqa: E402
from griglia_core import dc_matrix  # noqa: E402


def test_shin_e_potenza_sommano_a_uno_e_sono_nell_intervallo():
    odds = [2.10, 3.40, 3.60]
    for fn in (gv.devig_shin, gv.devig_power):
        p = fn(odds)
        assert p is not None
        assert abs(p.sum() - 1.0) < 1e-10
        assert np.all(p > 0) and np.all(p < 1)
        # favorito: la probabilita' piu' alta resta sul favorito (quota piu' bassa)
        assert np.argmax(p) == 0


def test_shin_e_potenza_quote_non_valide_restituiscono_none():
    assert gv.devig_shin([1.0, 3.0]) is None
    assert gv.devig_power([float("nan"), 3.0]) is None


def test_shin_su_margine_nullo_coincide_con_proporzionale():
    odds = [2.0, 4.0, 4.0]          # somma 1/o = 1: nessun margine
    np.testing.assert_allclose(gv.devig_shin(odds), gv.devig_prop(odds), atol=1e-9)
    np.testing.assert_allclose(gv.devig_power(odds), gv.devig_prop(odds), atol=1e-9)


def test_tau_produzione_coincide_con_dixon_coles_articolo():
    for lam, mu, rho in [(1.0, 1.5, -0.1), (1.7, 0.9, -0.15), (1.2, 1.2, 0.05)]:
        for cell, p, art, _pb in gv.tau_table(lam, mu, rho):
            assert abs(p - art) < 1e-12, (cell, p, art)


def test_tau_penaltyblog_e_scambiata_su_0_1_e_1_0():
    lam, mu, rho = 1.0, 1.5, -0.1
    tab = {c: (p, art, pb) for c, p, art, pb in gv.tau_table(lam, mu, rho)}
    assert abs(tab[(0, 1)][2] - tab[(1, 0)][1]) < 1e-12   # pb(0,1) = art(1,0)
    assert abs(tab[(1, 0)][2] - tab[(0, 1)][1]) < 1e-12   # pb(1,0) = art(0,1)
    assert abs(tab[(0, 0)][2] - tab[(0, 0)][1]) < 1e-12   # (0,0) e (1,1) identici
    assert abs(tab[(1, 1)][2] - tab[(1, 1)][1]) < 1e-12


def test_fit_rho_fisso_riproduce_approssimativamente_le_quote():
    # una partita con quote coerenti con un Poisson: il fit a rho fisso deve convergere
    m = dc_matrix(1.4, 1.1, -0.08)
    t = gv.grid_1x2_ou(m)
    lam, mu, res = gv.fit_fixed_rho(t[0], t[1], t[2], t[3], -0.08)
    assert res < 1e-6
    assert abs(lam - 1.4) < 1e-3 and abs(mu - 1.1) < 1e-3


def test_evento_e_complemento_sommano_a_uno():
    from griglia_core import _GG
    m = dc_matrix(1.3, 1.0, -0.05)
    p = gv.event_probs(m)
    p_no_gol = float(m.ravel() @ (~_GG).ravel().astype(float))
    assert abs(p[gv.EV_IDX["Gol"]] + p_no_gol - 1.0) < 1e-12
    assert np.all(p >= 0) and np.all(p <= 1 + 1e-12)
