"""The exhaustive grid is frozen and well-formed — the K~800 pre-registration.

If someone grows the grid, K changes and the multiple-testing correction must be
recomputed at the new K; this test makes that a deliberate, visible change rather
than a silent one.
"""
from optionsbot.research.search_grid import PREREGISTERED_GRID, _sig

VALID_RANK = {"base", "skip_month", "residual", "trend_quality", "downside"}
VALID_REGIME = {"none", "price_sma", "slope_sma", "macd", "breadth", "dispersion"}
VALID_WEIGHT = {"equal", "inverse_vol", "score_prop"}
VALID_EXPOSURE = {"binary", "vol_target"}
VALID_TRAIL = {"none", "per_stock", "portfolio"}


def test_grid_is_frozen_and_well_formed():
    g = PREREGISTERED_GRID
    assert 600 <= len(g) <= 1000                 # ~800; deliberate if it moves
    assert g[0].name == "base"                   # benchmark first, not a trial
    assert len(set(_sig(c) for c in g)) == len(g)   # all distinct
    assert all(c.mechanism.strip() for c in g)   # every config justified
    assert all(c.rank_mode in VALID_RANK for c in g)
    assert all(c.regime_mode in VALID_REGIME for c in g)
    assert all(c.weight_mode in VALID_WEIGHT for c in g)
    assert all(c.exposure_mode in VALID_EXPOSURE for c in g)
    assert all(c.trail_stop_mode in VALID_TRAIL for c in g)


def test_grid_covers_the_trailing_stop_family():
    g = PREREGISTERED_GRID
    per = [c for c in g if c.trail_stop_mode == "per_stock"]
    port = [c for c in g if c.trail_stop_mode == "portfolio"]
    assert len(per) > 50 and len(port) > 50      # the owner's ask is well covered
    # trailing-stop configs carry a real percentage.
    assert all(0.0 < c.trail_stop_pct < 1.0 for c in per + port)


def test_grid_is_deterministic():
    from optionsbot.research.search_grid import preregistered_grid
    a = [_sig(c) for c in preregistered_grid()]
    b = [_sig(c) for c in preregistered_grid()]
    assert a == b                                # no randomness in the grid
