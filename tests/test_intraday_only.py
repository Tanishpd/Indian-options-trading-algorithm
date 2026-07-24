"""Intraday-only short strangle. The two properties that make it "intraday-only":
the position is entered and exited on the SAME day (never held overnight), and the
exit at square-off is the quoted cost to close, not the expiry intrinsic.
"""
from datetime import date, datetime, time

import pytest

from optionsbot.config import CostConfig
from optionsbot.data.intraday import Bar
from optionsbot.instruments import Right
from optionsbot.research.short_strangle import StrangleParams
from optionsbot.research.intraday_only import run_day

EXPIRY = date(2026, 7, 23)                 # Thursday weekly
DAY = date(2026, 7, 21)                    # 2 DTE — enter and exit THIS day
LOT = 65
ZERO = CostConfig(brokerage_per_order=0, txn_charge_rate=0, sebi_fee_rate=0,
                  stamp_duty_rate=0, gst_rate=0)
# spot 25,000, offset 0.8% -> short call 25,200, short put 24,800; intraday window.
P = StrangleParams(offset_pct=0.008, strike_step=50.0, slippage_per_leg=0.0,
                   entry_start=time(9, 20), entry_end=time(12, 0),
                   squareoff=time(15, 25))

OPEN = datetime(2026, 7, 21, 9, 20)
CLOSE = datetime(2026, 7, 21, 15, 25)


def cbar(ts, strike, right, ltp, spot, volume=100):
    return Bar(ts=ts, expiry=EXPIRY, strike=strike, right=right, ltp=ltp,
               volume=volume, spot=spot)


def chain_at(ts, call_ltp, put_ltp, spot):
    return [cbar(ts, 25200.0, Right.CALL, call_ltp, spot),
            cbar(ts, 24800.0, Right.PUT, put_ltp, spot)]


def test_intraday_squares_off_same_day_at_quoted_value():
    # Enter 09:20 collecting 30+28=58. By 15:25 the legs are quoted 5+5=10, so we buy
    # them back for 10 -> gross (58-10)*65 = 3,120. NOT held overnight.
    bars = chain_at(OPEN, 30.0, 28.0, 25000.0) + chain_at(CLOSE, 5.0, 5.0, 25000.0)
    trade = run_day(bars, EXPIRY, LOT, P, ZERO)
    assert trade is not None
    assert trade.exit_reason == "squareoff"
    assert trade.entered_at.date() == trade.exited_at.date() == DAY   # never overnight
    assert trade.credit == pytest.approx(58.0)
    assert trade.exit_value == pytest.approx(10.0)                    # quoted, not intrinsic
    assert trade.gross == pytest.approx((58 - 10) * LOT)             # 3,120


def test_intraday_stop_fires_within_the_day():
    """A 2x-credit stop (threshold 116) fires intraday at 80+40=120 and books the loss
    the same day, rather than riding to the close."""
    p = StrangleParams(offset_pct=0.008, slippage_per_leg=0.0, stop_loss_mult=2.0,
                       entry_start=time(9, 20), entry_end=time(12, 0),
                       squareoff=time(15, 25))
    bars = (chain_at(OPEN, 30.0, 28.0, 25000.0)
            + chain_at(datetime(2026, 7, 21, 12, 30), 80.0, 40.0, 25400.0)   # value 120
            + chain_at(CLOSE, 5.0, 5.0, 25000.0))
    trade = run_day(bars, EXPIRY, LOT, p, ZERO)
    assert trade.exit_reason == "stop"
    assert trade.exited_at == datetime(2026, 7, 21, 12, 30)
    assert trade.entered_at.date() == trade.exited_at.date()          # still same day
    assert trade.gross == pytest.approx((58 - 120) * LOT)            # -4,030, capped


def test_intraday_skips_when_no_entry_in_window():
    # Only a 14:00 chain exists — outside the 09:20-12:00 entry window -> no trade.
    bars = chain_at(datetime(2026, 7, 21, 14, 0), 30.0, 28.0, 25000.0)
    assert run_day(bars, EXPIRY, LOT, P, ZERO) is None
