from datetime import date

import pytest

from optionsbot.backtest.data import QuoteBar
from optionsbot.fills import limit_fill_price, protection_band_limit
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
