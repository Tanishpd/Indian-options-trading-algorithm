"""Naked short strangle. The two hand-computed cases are the whole risk story:
the index finishing between the strikes keeps the full credit; a modest breach
loses many times that credit, because there are no wings.
"""
from datetime import date, datetime

import pytest

from optionsbot.config import CostConfig
from optionsbot.data.intraday import Bar
from optionsbot.instruments import Right
from optionsbot.research.short_strangle import StrangleParams, run_cycle

EXPIRY = date(2026, 7, 21)
LOT = 65
ZERO = CostConfig(brokerage_per_order=0, txn_charge_rate=0, sebi_fee_rate=0,
                  stamp_duty_rate=0, gst_rate=0)
# spot 25,000, offset 0.8% -> short call 25,200, short put 24,800; frictionless.
P = StrangleParams(offset_pct=0.008, strike_step=50.0, slippage_per_leg=0.0)


def cbar(ts, strike, right, ltp, spot, volume=100):
    return Bar(ts=ts, expiry=EXPIRY, strike=strike, right=right, ltp=ltp,
               volume=volume, spot=spot)


def chain_at(ts, call_ltp, put_ltp, spot):
    return [cbar(ts, 25200.0, Right.CALL, call_ltp, spot),
            cbar(ts, 24800.0, Right.PUT, put_ltp, spot)]


ENTRY = datetime(2026, 7, 16, 10, 0)      # 5 DTE, inside the window
SETTLE = datetime(2026, 7, 21, 15, 20)    # expiry day


def test_strangle_keeps_full_credit_when_index_expires_between_strikes():
    # credit = 30 + 28 = 58/share. Index finishes at 25,000 -> both legs OTM.
    bars = chain_at(ENTRY, 30.0, 28.0, 25000.0) + chain_at(SETTLE, 5.0, 5.0, 25000.0)
    trade, why = run_cycle(bars, EXPIRY, LOT, P, ZERO)
    assert trade is not None and why == ""
    assert trade.credit == pytest.approx(58.0)
    assert trade.exit_value == pytest.approx(0.0)
    assert not trade.breached and trade.won
    assert trade.gross == pytest.approx(58 * LOT)          # 3,770


def test_strangle_loss_dwarfs_the_credit_on_a_modest_breach():
    """A 2.8% up-move puts the 25,200 call 500 points ITM. The strangle collected
    58 and settles owing 500: the loss is (58-500)*65 = -28,730 on ONE lot -- 7.6x
    the credit. This asymmetry (no wings) is the whole point of the study."""
    bars = chain_at(ENTRY, 30.0, 28.0, 25000.0) + chain_at(SETTLE, 500.0, 0.0, 25700.0)
    trade, _ = run_cycle(bars, EXPIRY, LOT, P, ZERO)
    assert trade.breached and not trade.won
    assert trade.exit_value == pytest.approx(500.0)        # 25,700 - 25,200
    assert trade.gross == pytest.approx((58 - 500) * LOT)  # -28,730
    assert trade.gross < -7 * (58 * LOT)                   # loss > 7x the credit collected


def test_strangle_hard_stop_caps_a_grind_loss():
    """credit 58; a 2x-credit stop fires when the cost-to-close reaches 116.
    At 80+40=120 (day 17, well before expiry) the stop books -4,030 instead of
    letting the position run to a bigger settlement loss."""
    p = StrangleParams(offset_pct=0.008, slippage_per_leg=0.0, stop_loss_mult=2.0)
    bars = (chain_at(ENTRY, 30.0, 28.0, 25000.0)
            + chain_at(datetime(2026, 7, 17, 11, 0), 80.0, 40.0, 25400.0)   # value 120 -> stop
            + chain_at(SETTLE, 5.0, 5.0, 25000.0))
    trade, _ = run_cycle(bars, EXPIRY, LOT, p, ZERO)
    assert trade.exit_reason == "stop"
    assert trade.exited_at == datetime(2026, 7, 17, 11, 0)
    assert trade.exit_value == pytest.approx(120.0)
    assert trade.gross == pytest.approx((58 - 120) * LOT)      # -4,030, capped


def test_strangle_profit_target_locks_a_gain():
    """A 50%-of-credit target exits when the cost-to-close falls to 29. At 15+10=25
    it books +2,145 rather than risking the last of the premium."""
    p = StrangleParams(offset_pct=0.008, slippage_per_leg=0.0, profit_target_frac=0.5)
    bars = (chain_at(ENTRY, 30.0, 28.0, 25000.0)
            + chain_at(datetime(2026, 7, 17, 11, 0), 15.0, 10.0, 25000.0)   # value 25 -> target
            + chain_at(SETTLE, 5.0, 5.0, 25000.0))
    trade, _ = run_cycle(bars, EXPIRY, LOT, p, ZERO)
    assert trade.exit_reason == "target"
    assert trade.exit_value == pytest.approx(25.0)
    assert trade.gross == pytest.approx((58 - 25) * LOT)       # 2,145


def test_strangle_skips_when_no_tradeable_entry():
    # A zero-volume entry minute is not tradeable -> no fill, cycle skipped.
    bars = ([cbar(ENTRY, 25200.0, Right.CALL, 30.0, 25000.0, volume=0),
             cbar(ENTRY, 24800.0, Right.PUT, 28.0, 25000.0, volume=0)]
            + chain_at(SETTLE, 5.0, 5.0, 25000.0))
    trade, why = run_cycle(bars, EXPIRY, LOT, P, ZERO)
    assert trade is None and why == "no_entry"


def chain4(ts, call_ltp, put_ltp, wc_ltp, wp_ltp, spot):
    """Same two shorts as chain_at, plus the 400-point wings at 25,600 / 24,400."""
    return [cbar(ts, 25200.0, Right.CALL, call_ltp, spot),
            cbar(ts, 24800.0, Right.PUT, put_ltp, spot),
            cbar(ts, 25600.0, Right.CALL, wc_ltp, spot),
            cbar(ts, 24400.0, Right.PUT, wp_ltp, spot)]


def test_wings_cap_the_loss_on_the_identical_position():
    """The apples-to-apples hedge test. SAME shorts as the naked breach case
    (25,200/24,800, index finishing at 25,700 -> short call 500 ITM), but with
    400-point wings bought at entry. The long 25,600 call is 100 ITM at
    settlement, so the call spread is worth 400, not 500 -- the loss is CAPPED at
    the wing width. Credit falls to 58-18=40 (the wings cost premium), so the
    booked loss is exactly (40-400)*65 = -23,400 = the defined max loss, versus
    the naked -28,730. Less tail, but paid for with credit: no free lunch."""
    p = StrangleParams(offset_pct=0.008, strike_step=50.0, slippage_per_leg=0.0,
                       wing_points=400.0)
    bars = (chain4(ENTRY, 30.0, 28.0, 10.0, 8.0, 25000.0)
            + chain4(SETTLE, 500.0, 0.0, 100.0, 0.0, 25700.0))
    trade, why = run_cycle(bars, EXPIRY, LOT, p, ZERO)
    assert trade is not None and why == ""
    assert trade.hedged                                    # wings were in place
    assert trade.credit == pytest.approx(40.0)             # 58 collected - 18 for wings
    assert trade.exit_value == pytest.approx(400.0)        # capped at wing width, not 500
    assert trade.gross == pytest.approx((40 - 400) * LOT)  # -23,400 defined max loss
    assert trade.gross == pytest.approx(-(400 - 40) * LOT)  # = (wing_width - credit) * lot
    assert trade.gross > (58 - 500) * LOT                  # strictly less loss than naked -28,730


def test_wings_absent_when_untradeable_falls_back_to_naked():
    """If the wing strikes have no volume at entry, we do NOT skip the cycle --
    we trade it naked and flag hedged=False. This is the honest handling that the
    condor engine gets wrong by dropping the whole (un-hedgeable) cycle."""
    p = StrangleParams(offset_pct=0.008, strike_step=50.0, slippage_per_leg=0.0,
                       wing_points=400.0)
    entry = (chain_at(ENTRY, 30.0, 28.0, 25000.0)             # shorts tradeable
             + [cbar(ENTRY, 25600.0, Right.CALL, 10.0, 25000.0, volume=0),  # wings dead
                cbar(ENTRY, 24400.0, Right.PUT, 8.0, 25000.0, volume=0)])
    bars = entry + chain_at(SETTLE, 500.0, 0.0, 25700.0)
    trade, why = run_cycle(bars, EXPIRY, LOT, p, ZERO)
    assert trade is not None and why == ""
    assert not trade.hedged                                 # fell back to naked
    assert trade.credit == pytest.approx(58.0)              # full naked credit, no wings
    assert trade.gross == pytest.approx((58 - 500) * LOT)   # naked -28,730, UNBOUNDED tail
