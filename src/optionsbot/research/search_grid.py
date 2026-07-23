"""The exhaustive closes-only grid — the frozen pre-registration for the K~800
sweep (docs/16).

Same discipline as `search_configs.py`, at scale: this grid is committed BEFORE
the cross-validation window is touched, and K is exactly the number of distinct
configs it generates. With ~800 highly-correlated candidates the multiple-testing
correction is severe — that is the point. The verdict is decided by Romano-Wolf
FWER-adjusted p-values, CSCV/PBO, and Deflated Sharpe at the true K, not by the
best in-sample Sharpe.

Every config is a real closes-only strategy (nothing here needs highs/lows or
volume). The grid is single-axis sweeps off the base plus a set of high-value
two-way interactions (trailing-stop x regime, rank x regime, exposure x regime,
weighting x regime, trailing-stop x rank, trailing-stop x exposure). Duplicates
(including anything equal to base) are removed, so K is stable and honest.
"""
from __future__ import annotations

import itertools
from dataclasses import fields, replace

from .strategy_search import StrategyConfig
from .search_configs import BASE

# -- axis grids (each entry is a dict of field overrides off BASE) ---------

REGIMES: list[dict] = [
    {"regime_mode": "none"},
    {"regime_mode": "price_sma", "regime_sma": 100},
    {"regime_mode": "price_sma", "regime_sma": 150},
    {"regime_mode": "price_sma", "regime_sma": 200},
    {"regime_mode": "price_sma", "regime_sma": 250},
    {"regime_mode": "slope_sma", "regime_sma": 150, "slope_k": 21},
    {"regime_mode": "slope_sma", "regime_sma": 200, "slope_k": 21},
    {"regime_mode": "slope_sma", "regime_sma": 200, "slope_k": 63},
    {"regime_mode": "macd", "macd_fast": 12, "macd_slow": 26, "macd_signal": 9},
    {"regime_mode": "macd", "macd_fast": 8, "macd_slow": 21, "macd_signal": 5},
    {"regime_mode": "breadth", "breadth_ma": 50, "breadth_thresh": 0.5},
    {"regime_mode": "breadth", "breadth_ma": 100, "breadth_thresh": 0.5},
    {"regime_mode": "breadth", "breadth_ma": 50, "breadth_thresh": 0.5,
     "breadth_combine": True},
    {"regime_mode": "dispersion", "disp_span": 63, "exposure_floor": 0.3},
    {"regime_mode": "dispersion", "disp_span": 126, "exposure_floor": 0.3},
]

RANKS: list[dict] = [
    {"rank_mode": "base"},
    {"rank_mode": "skip_month", "skip": 21},
    {"rank_mode": "skip_month", "skip": 42},
    {"rank_mode": "residual", "resid_lookback": 126},
    {"rank_mode": "residual", "resid_lookback": 252},
    {"rank_mode": "trend_quality", "tq_span": 126, "tq_weight": 0.5},
    {"rank_mode": "trend_quality", "tq_span": 252, "tq_weight": 0.3},
    {"rank_mode": "downside"},
]

WEIGHTS: list[dict] = [
    {"weight_mode": "equal"},
    {"weight_mode": "inverse_vol", "weight_vol_span": 63},
    {"weight_mode": "inverse_vol", "weight_vol_span": 126},
    {"weight_mode": "score_prop"},
]

EXPOSURES: list[dict] = [
    {"exposure_mode": "binary"},
    {"exposure_mode": "vol_target", "target_vol": 0.10, "vol_lookback": 63},
    {"exposure_mode": "vol_target", "target_vol": 0.15, "vol_lookback": 63},
    {"exposure_mode": "vol_target", "target_vol": 0.20, "vol_lookback": 63},
    {"exposure_mode": "vol_target", "target_vol": 0.15, "vol_lookback": 21},
    {"exposure_mode": "vol_target", "target_vol": 0.15, "vol_lookback": 126},
    {"exposure_mode": "vol_target", "target_vol": 0.15, "vol_lookback": 63,
     "exposure_floor": 0.3},
    {"exposure_mode": "vol_target", "target_vol": 0.10, "vol_lookback": 63,
     "exposure_floor": 0.3},
]

_TRAIL_PCTS = (0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30)
TRAILS: list[dict] = (
    [{"trail_stop_mode": "none"}]
    + [{"trail_stop_mode": "per_stock", "trail_stop_pct": p} for p in _TRAIL_PCTS]
    + [{"trail_stop_mode": "portfolio", "trail_stop_pct": p} for p in _TRAIL_PCTS]
)

TOPNS: list[dict] = [{"top_n": n} for n in (15, 20, 25, 30, 40, 50)]

LOOKBACKS: list[dict] = [
    {"lookback_short": 126, "lookback_long": 252},   # base
    {"lookback_short": 63, "lookback_long": 126},
    {"lookback_short": 126, "lookback_long": 189},
    {"lookback_short": 189, "lookback_long": 252},
    {"lookback_short": 21, "lookback_long": 252},
]

# high-value two-way interactions to cross (trailing stops are the owner's ask,
# so they cross widely)
_PAIRS = [
    (TRAILS, REGIMES), (TRAILS, RANKS), (TRAILS, EXPOSURES),
    (RANKS, REGIMES), (EXPOSURES, REGIMES), (WEIGHTS, REGIMES),
]

_IGNORE = {"name", "mechanism"}


def _sig(cfg: StrategyConfig) -> tuple:
    return tuple(getattr(cfg, f.name) for f in fields(cfg) if f.name not in _IGNORE)


def _describe(overrides: dict) -> str:
    return "grid: " + ", ".join(f"{k}={v}" for k, v in overrides.items())


def preregistered_grid() -> list[StrategyConfig]:
    """Base first, then every DISTINCT closes-only config the grid defines. K is
    len() of the returned list; it is stable across runs (no randomness)."""
    seen = {_sig(BASE)}
    out: list[StrategyConfig] = [BASE]

    def add(overrides: dict) -> None:
        cfg = replace(BASE, name="", mechanism="", **overrides)
        s = _sig(cfg)
        if s in seen:
            return
        seen.add(s)
        out.append(replace(cfg, name=f"g{len(out):04d}", mechanism=_describe(overrides)))

    for grid in (REGIMES, RANKS, WEIGHTS, EXPOSURES, TRAILS, TOPNS, LOOKBACKS):
        for o in grid:
            add(o)
    for a, b in _PAIRS:
        for oa, ob in itertools.product(a, b):
            add({**oa, **ob})
    return out


PREREGISTERED_GRID = preregistered_grid()
