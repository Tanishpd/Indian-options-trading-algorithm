"""Protection-band limit-order fill simulation.

Market orders are banned for algos (docs/03), so every fill in backtest and
live is a limit order. Simulation is deliberately conservative: fills happen
at the limit price (never better), and a gap through the band is a no-fill —
mirroring the real regime where protection-band orders guarantee nothing on gaps.
"""
from __future__ import annotations

from .instruments import Side


TICK_SIZE = 0.05  # NSE/BSE option tick — limits off this grid are exchange-invalid


def to_tick(price: float, side: Side, tick: float = TICK_SIZE) -> float:
    """Snap a limit price onto the exchange tick grid, conservatively:
    BUY rounds up, SELL rounds down (never better than intended)."""
    import math

    steps = price / tick
    snapped = max(0.0, round(
        (math.ceil(steps - 1e-9) if side is Side.BUY else math.floor(steps + 1e-9)) * tick, 2
    ))
    # An option cannot trade below one tick, so a positive price must never snap
    # to zero. It otherwise happens on every exit of a leg sitting at the 0.05
    # minimum: the pad puts the SELL reference at 0.049x, rounding down gives a
    # limit of 0.00, and a zero SELL limit is not a low price -- it is "accept
    # anything". The broker crosses it and books zero premium for a leg that was
    # worth 0.05, giving away Rs 3.25 per 65-share leg for nothing.
    if price > 0.0 and snapped < tick:
        return tick
    return snapped


def protection_band_limit(reference_price: float, side: Side, band_pct: float) -> float:
    """Limit price mimicking a broker protection band around a reference price."""
    if reference_price < 0:
        raise ValueError("reference price must be non-negative")
    if not 0.0 <= band_pct < 1.0:
        raise ValueError(f"band_pct must be in [0, 1); got {band_pct}")
    return reference_price * (1 + band_pct if side is Side.BUY else 1 - band_pct)


def limit_fill_price(side: Side, limit_price: float, bar) -> float | None:
    """Fill price for a limit order against an OHLC bar, or None if unfilled.

    `bar` needs .open/.high/.low/.close attributes. BUY fills only if the bar
    traded at or below the limit; SELL only at or above. Fills are assumed at
    the limit itself — no price improvement.
    """
    if limit_price < 0:
        raise ValueError("limit price must be non-negative")
    side = Side(side)
    if side is Side.BUY:
        return limit_price if bar.low <= limit_price else None
    return limit_price if bar.high >= limit_price else None
