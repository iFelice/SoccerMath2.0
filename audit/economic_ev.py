"""Primitive economiche condivise dagli audit.

Le probabilita' de-vigate descrivono il mercato, ma non sono una soglia di
esecuzione. Una puntata a quota decimale grezza e' eseguibile soltanto quando
il suo valore atteso unitario e' strettamente positivo.
"""
from __future__ import annotations

import math
from typing import Iterable, Optional, Sequence, Tuple


def expected_value(probability: float, decimal_odds: float) -> float:
    """Ritorna ``p * quota - 1``; NaN per input non economici/non finiti."""
    try:
        p, q = float(probability), float(decimal_odds)
    except (TypeError, ValueError):
        return math.nan
    if not (math.isfinite(p) and math.isfinite(q)) or not 0 <= p <= 1 or q <= 1:
        return math.nan
    return p * q - 1.0


def select_positive_ev(probabilities: Sequence[float], odds: Sequence[float],
                       minimum_ev: float = 0.0) -> Optional[Tuple[int, float]]:
    """Seleziona l'esito col massimo EV, solo se EV > ``minimum_ev``."""
    if len(probabilities) != len(odds):
        raise ValueError("probabilities e odds devono avere la stessa lunghezza")
    evs = [expected_value(p, q) for p, q in zip(probabilities, odds)]
    valid = [(i, ev) for i, ev in enumerate(evs) if math.isfinite(ev)]
    if not valid:
        return None
    chosen = max(valid, key=lambda item: item[1])
    return chosen if chosen[1] > minimum_ev else None


def is_positive_ev(probability: float, decimal_odds: float) -> bool:
    ev = expected_value(probability, decimal_odds)
    return math.isfinite(ev) and ev > 0.0
