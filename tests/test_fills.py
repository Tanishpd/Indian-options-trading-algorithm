from datetime import date

import pytest

from optionsbot.backtest.data import QuoteBar
from optionsbot.fills import limit_fill_price, protection_band_limit, to_tick
from optionsbot.instruments import Right, Side


def bar(o, h, l, c):
    return QuoteBar(
        day=date(2026, 7, 7), index="NIFTY", expiry=date(2026, 7, 14),
        strike=25900, right=Right.CALL, open=o, high=h, low=l, close=c,
    )


def test_buy_fills_at_limit_when_touched():
    assert limit_fill_price(Side.BUY, 50.0, bar(52, 55, 49, 51)) == 50.0


def test_buy_no_fill_when_market_stays_above():
    assert limit_fill_price(Side.BUY, 50.0, bar(52, 55, 51, 53)) is None


def test_sell_fills_at_limit_when_touched():
    assert limit_fill_price(Side.SELL, 50.0, bar(48, 51, 47, 49)) == 50.0


def test_sell_no_fill_on_gap_down():
    assert limit_fill_price(Side.SELL, 50.0, bar(45, 49, 43, 44)) is None


def test_no_price_improvement_assumed():
    # Market opened below the buy limit; conservative sim still fills at limit.
    assert limit_fill_price(Side.BUY, 50.0, bar(45, 48, 44, 46)) == 50.0


def test_protection_band():
    assert protection_band_limit(100.0, Side.BUY, 0.05) == pytest.approx(105.0)
    assert protection_band_limit(100.0, Side.SELL, 0.05) == pytest.approx(95.0)
    assert protection_band_limit(0.0, Side.SELL, 0.05) == 0.0


def test_protection_band_rejects_nonsense_band():
    # band_pct=5 (meant 5%) would send every SELL limit to zero; fail loudly.
    with pytest.raises(ValueError, match="band_pct"):
        protection_band_limit(100.0, Side.SELL, 5.0)


def test_bar_validates_ohlc():
    with pytest.raises(ValueError, match="inconsistent OHLC"):
        bar(52, 51, 53, 52)  # high < low


def test_positive_price_never_snaps_to_a_zero_limit():
    """A SELL limit of 0.00 is not a low price, it is "accept anything". The
    strategy's exit pad puts a leg sitting at the 0.05 minimum tick at 0.049x,
    which floors to zero; the broker then crosses it and books zero premium for
    a leg worth Rs 3.25 at lot 65. Every exit of a near-worthless wing gave that
    away, on both the profit-target and stop paths."""
    for pad_mult in (1.0, 2.5, 5.0):                 # the full pad range
        reference = 0.05 * (1 - 0.005 * pad_mult)
        assert to_tick(reference, Side.SELL) == 0.05
    # The squareoff/kill-switch flatten path reaches the same floor at every
    # configured protection band, and deep-OTM wings sit at 0.05 precisely on
    # expiry day, which is when that path runs.
    for band in (0.05, 0.10, 0.30):
        assert to_tick(protection_band_limit(0.05, Side.SELL, band), Side.SELL) == 0.05
    assert to_tick(0.0, Side.SELL) == 0.0            # genuinely zero stays zero
    assert to_tick(0.049, Side.BUY) == 0.05          # BUY already rounded up


def test_sell_still_rounds_down_above_one_tick():
    """The zero-clamp must not turn into rounding up generally: a SELL limit
    above one tick still rounds down, never to a better price than intended."""
    assert to_tick(0.34, Side.SELL) == 0.30
    assert to_tick(1.99, Side.SELL) == 1.95
    assert to_tick(0.34, Side.BUY) == 0.35
