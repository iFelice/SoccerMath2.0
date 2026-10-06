"""Controlli piccoli e deterministici per il triage Elo (solo audit)."""
from __future__ import annotations

import numpy as np

from elo_drift_triage import (
    BOOT_SEED,
    _CarryRatings,
    _seed_for_variant,
    paired_block_bootstrap,
)


def _record(never=False, absence=1):
    return {
        "team": "New", "never_seen": never, "anni_assenza": absence,
        "active_teams": ["A", "B"],
    }


def test_seed_variants_are_fixed_and_not_estimated():
    carry = _CarryRatings({"A": 1510.0, "B": 1490.0, "New": 1320.0})
    rec = _record(never=False, absence=2)
    assert _seed_for_variant("S1", rec, carry)[0] == 1500.0
    assert _seed_for_variant("S2", rec, carry)[0] == 1450.0
    assert _seed_for_variant("S3", rec, carry)[0] == 1400.0
    # 0.5**2 sul rating stantio verso 1400.
    assert _seed_for_variant("S4", rec, carry)[0] == 1380.0
    assert _seed_for_variant("S4", _record(never=True), carry)[0] == 1400.0


def test_block_bootstrap_is_paired_and_reproducible():
    s0 = np.array([0.2, 0.3, 0.4, 0.5])
    alt = s0 - 0.1
    blocks = ["A|2024", "A|2024", "B|2024", "B|2024"]
    a = paired_block_bootstrap(alt, s0, blocks, n_boot=200, seed=BOOT_SEED)
    b = paired_block_bootstrap(alt, s0, blocks, n_boot=200, seed=BOOT_SEED)
    assert a == b
    assert a["point"] < 0
    assert a["n_blocks"] == 2
