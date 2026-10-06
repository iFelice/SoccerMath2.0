import math
from economic_ev import expected_value, select_positive_ev

def test_negative_ev_despite_devig_disagreement():
    # p > 0.50 fair, but p < 1/1.90: must not execute.
    assert expected_value(.51, 1.90) < 0
    assert select_positive_ev([.51, .49], [1.90, 1.90]) is None

def test_selects_maximum_strictly_positive_ev():
    assert select_positive_ev([.6, .41], [1.8, 2.7]) == (1, pytest.approx(.107))

def test_invalid_input_is_not_selected():
    assert math.isnan(expected_value(.5, float('nan')))
    assert select_positive_ev([.5], [float('nan')]) is None

import pytest
