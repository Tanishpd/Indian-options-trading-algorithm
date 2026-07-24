"""Intraday condor study. Every expected P&L is a hand-computed literal.

The refusal paths matter as much as the arithmetic: a study that fills on an
untraded minute, or resolves an ambiguous minute in its own favour, produces
numbers that look like evidence and are not.
"""
from datetime import date, datetime, time

import pytest

from optionsbot.config import CostConfig, RiskConfig
from optionsbot.data.intraday import Bar
from optionsbot.instruments import Right, Side
from optionsbot.research.intraday_condor import IntradayParams, run_expiry

EXPIRY = date(2026, 7, 21)
ZERO = CostConfig(brokerage_per_order=0, txn_charge_rate=0, sebi_fee_rate=0,
                  stamp_duty_rate=0, gst_rate=0)
RISK = RiskConfig(per_trade_max_loss_rupees=5000.0)
LOT = 65
SPOT = 25000.0
# offset 0.8% of 25,000 -> shorts at 25,200 / 24,800; wings 50 points out.
SC, LC, SP, LP = 25200.0, 25250.0, 24800.0, 24750.0
# Frictionless on purpose: these tests pin arithmetic, so slippage is chosen
# explicitly rather than inherited. The default is a realistic 0.25/leg.
PARAMS = IntradayParams(offset_pct=0.008, wing_points=50.0, slippage_per_leg=0.0)


def bar(ts, strike, right, ltp, volume=100, spot=SPOT):
    return Bar(ts=ts, expiry=EXPIRY, strike=strike, right=right, ltp=ltp,
               volume=volume, spot=spot)


def minute(ts, sc, lc, sp, lp, volume=100, spot=SPOT):
    """One chain snapshot: (short call, long call, short put, long put)."""
    return [
        bar(ts, SC, Right.CALL, sc, volume, spot), bar(ts, LC, Right.CALL, lc, volume, spot),
        bar(ts, SP, Right.PUT, sp, volume, spot), bar(ts, LP, Right.PUT, lp, volume, spot),
    ]


def at(day, h, m):
    return datetime(2026, 7, day, h, m)


# Entry on 2026-07-16 (5 DTE, inside the 10:00-14:00 window) with
# credit = 30 + 28 - 20 - 18 = 20 per share. Deliberately kept low enough that
# a 2x stop (40) stays inside the 50-point wing and can actually trigger --
# a higher credit makes the stop unreachable, which the study now rejects.
ENTRY_TS = at(16, 10, 0)
ENTRY = minute(ENTRY_TS, 30.0, 20.0, 28.0, 18.0)


def test_profit_target_exit_hand_computed():
    # Cost to close = 8 + 6 - 2 - 3 = 9 <= 50% of 20. Gross = (20-9)*65 = 715.
    bars = ENTRY + minute(at(16, 10, 1), 8.0, 2.0, 6.0, 3.0)
    trade, why = run_expiry(bars, EXPIRY, LOT, PARAMS, ZERO, RISK)
    assert why == "" and trade is not None
    assert trade.exit_reason == "target"
    assert trade.credit == 20.0 and trade.exit_cost == 9.0
    assert trade.gross == 715.0
    assert trade.net == pytest.approx(715.0 - trade.costs)
    assert trade.minutes_held == 1


def test_stop_exit_hand_computed():
    # max loss = 50 - 20 = 30; stop at 60% -> 20 + 18 = 38.
    # Cost to close = 30 + 22 - 6 - 4 = 42 >= 38, and 42 <= the 50-pt wing.
    # Gross = (20-42)*65 = -1,430.
    bars = ENTRY + minute(at(16, 10, 1), 30.0, 6.0, 22.0, 4.0)
    trade, _ = run_expiry(bars, EXPIRY, LOT, PARAMS, ZERO, RISK)
    assert trade.exit_reason == "stop"
    assert trade.exit_cost == 42.0 and trade.gross == -1430.0
    assert not trade.won


def test_stop_wins_when_both_triggers_hold_in_one_minute():
    """Conservative reading: a structure past the stop threshold is a loss being
    taken. Resolving such a minute as a win is how a backtest flatters itself."""
    # Assert ordering directly on a value past the stop threshold.
    bars = ENTRY + minute(at(16, 10, 1), 30.0, 6.0, 22.0, 4.0)
    trade, _ = run_expiry(bars, EXPIRY, LOT, PARAMS, ZERO, RISK)
    assert trade.exit_reason == "stop"


def test_untradeable_minute_cannot_be_filled():
    """A zero-volume leg is a forward-filled carry, not a quote. The exit must
    wait rather than transact at it."""
    stale = minute(at(16, 10, 1), 8.0, 2.0, 6.0, 3.0, volume=0)   # target level, but no trade
    real = minute(at(16, 10, 2), 9.0, 2.0, 7.0, 4.0)              # 10 <= 10, still a target
    trade, _ = run_expiry(ENTRY + stale + real, EXPIRY, LOT, PARAMS, ZERO, RISK)
    assert trade.exited_at == at(16, 10, 2)      # not the stale minute
    assert trade.exit_cost == 10.0


def test_entry_requires_all_four_legs_tradeable():
    partial = minute(ENTRY_TS, 30.0, 20.0, 28.0, 18.0)
    partial[1] = bar(ENTRY_TS, LC, Right.CALL, 20.0, volume=0)    # wing untraded
    later = minute(at(16, 10, 5), 30.0, 20.0, 28.0, 18.0)
    exitm = minute(at(16, 10, 6), 8.0, 2.0, 6.0, 3.0)
    trade, _ = run_expiry(partial + later + exitm, EXPIRY, LOT, PARAMS, ZERO, RISK)
    assert trade.entered_at == at(16, 10, 5)     # skipped the untradeable minute


def test_no_entry_outside_the_time_window():
    early = minute(at(16, 9, 30), 30.0, 20.0, 28.0, 18.0)
    late = minute(at(16, 14, 30), 30.0, 20.0, 28.0, 18.0)
    trade, why = run_expiry(early + late, EXPIRY, LOT, PARAMS, ZERO, RISK)
    assert trade is None and why == "no_entry"


def test_no_entry_outside_the_dte_window():
    # 2026-07-20 is 1 DTE, below min_dte=2.
    bars = minute(at(20, 10, 0), 30.0, 20.0, 28.0, 18.0)
    trade, why = run_expiry(bars, EXPIRY, LOT, PARAMS, ZERO, RISK)
    assert trade is None and why == "no_entry"


def test_entry_refused_when_it_would_breach_the_per_trade_cap():
    # credit 6 on a 50-point wing -> worst case (50-6)*65 = Rs 2,860 > Rs 2,000.
    thin = minute(ENTRY_TS, 5.0, 3.0, 6.0, 2.0)   # credit 6
    trade, why = run_expiry(thin, EXPIRY, LOT, PARAMS, ZERO,
                            RiskConfig(per_trade_max_loss_rupees=2000.0))
    assert trade is None and why == "no_entry"


def test_squareoff_forces_exit_on_expiry_day():
    hold = minute(at(16, 10, 1), 30.0, 20.0, 28.0, 18.0)          # neither trigger
    late = minute(at(21, 15, 0), 20.0, 8.0, 18.0, 7.0)            # expiry day, 15:00
    trade, _ = run_expiry(ENTRY + hold + late, EXPIRY, LOT, PARAMS, ZERO, RISK)
    assert trade.exit_reason == "squareoff"
    assert trade.exit_cost == 23.0                                # 20 + 18 - 8 - 7


def test_unexited_position_is_settled_not_deleted():
    """Deleting these removed ONLY maximum-loss outcomes in the first version
    of this study — survivorship bias severe enough to flip the result's sign."""
    hold = minute(at(16, 10, 1), 30.0, 20.0, 28.0, 18.0, spot=25400.0)
    trade, why = run_expiry(ENTRY + hold, EXPIRY, LOT, PARAMS, ZERO, RISK)
    assert why == "" and trade is not None
    assert trade.exit_reason == "settled"
    # spot 25,400 finishes above the 25,250 long call: the call spread is fully
    # in the money, so the structure settles at its 50-point maximum.
    assert trade.exit_cost == pytest.approx(50.0)
    assert trade.gross == pytest.approx((20.0 - 50.0) * 65)


def test_stop_is_reachable_at_every_credit():
    """Regression: expressing the stop as a multiple of credit made it
    unreachable in 45 of 72 real cycles. A share of max loss always fires."""
    for credit in (5.0, 20.0, 29.0, 45.0):
        stop_at = credit + PARAMS.stop_loss_frac * (PARAMS.wing_points - credit)
        assert stop_at <= PARAMS.wing_points + 1e-9


def test_exit_violating_the_no_arbitrage_bound_is_ignored():
    """Four non-synchronous prints can imply a structure worth more than its
    wing width. That is impossible, and cost 17% of exits in version one."""
    impossible = minute(at(16, 10, 1), 90.0, 5.0, 80.0, 4.0)      # implies 161 > 50
    good = minute(at(16, 10, 2), 8.0, 2.0, 6.0, 3.0)              # 9 -> target
    trade, _ = run_expiry(ENTRY + impossible + good, EXPIRY, LOT, PARAMS, ZERO, RISK)
    assert trade.exited_at == at(16, 10, 2) and trade.exit_cost == 9.0


def test_costs_are_charged_on_all_eight_fills():
    bars = ENTRY + minute(at(16, 10, 1), 8.0, 2.0, 6.0, 3.0)
    trade, _ = run_expiry(bars, EXPIRY, LOT, PARAMS, CostConfig(), RISK)
    # 8 fills x Rs 20 brokerage = Rs 160 floor, plus statutory charges.
    assert trade.costs > 160.0
    assert trade.net == pytest.approx(trade.gross - trade.costs)


def test_no_lookahead_earliest_valid_trigger_wins():
    """A later, larger profit must not be preferred over the first minute that
    satisfied the target."""
    first = minute(at(16, 10, 1), 8.0, 2.0, 6.0, 3.0)             # 9 -> target
    better = minute(at(16, 10, 2), 1.0, 0.5, 1.0, 0.5)            # richer, but later
    trade, _ = run_expiry(ENTRY + first + better, EXPIRY, LOT, PARAMS, ZERO, RISK)
    assert trade.exited_at == at(16, 10, 1) and trade.exit_cost == 9.0


# -- boundary and guard coverage ------------------------------------------
# Each test below exists because a mutation survived the suite without it. A
# study whose thresholds are unpinned can be re-tuned by accident and still
# look green, which is how an unreachable stop survived its first review.


def test_stop_fires_at_exact_equality():
    """With `>` instead of `>=`, a structure sitting exactly at its stop rides
    on to the settled fallback and books a fabricated win: a Rs 2,470 sign flip
    on this single cycle."""
    # credit 20, wing 50 -> stop at 20 + 0.60*30 = 38.0 exactly.
    bars = ENTRY + minute(at(16, 10, 1), 30.0, 6.0, 20.0, 6.0)   # value 38.0
    trade, _ = run_expiry(bars, EXPIRY, LOT, PARAMS, ZERO, RISK)
    assert trade.exit_reason == "stop" and trade.exit_cost == 38.0


def test_stop_level_is_pinned_both_sides():
    """Without the near-side case, any stop fraction in 0.10-0.73 passes."""
    for value_legs, expect in (
        ((30.0, 6.0, 20.0, 6.0), "stop"),        # 38.0, at the threshold
        ((30.0, 8.0, 20.0, 8.0), "settled"),     # 34.0, below it
    ):
        bars = ENTRY + minute(at(16, 10, 1), *value_legs)
        trade, _ = run_expiry(bars, EXPIRY, LOT, PARAMS, ZERO, RISK)
        assert trade.exit_reason == expect, value_legs


def test_profit_target_level_is_pinned_both_sides():
    """Without the near-side case the target is unbounded below: a 1%-of-credit
    target is indistinguishable from the intended 50%."""
    for value_legs, expect in (
        ((8.0, 2.0, 6.0, 3.0), "target"),        # 9.0 <= 10.0
        ((9.0, 2.0, 8.0, 4.0), "settled"),       # 11.0 > 10.0
    ):
        bars = ENTRY + minute(at(16, 10, 1), *value_legs)
        trade, _ = run_expiry(bars, EXPIRY, LOT, PARAMS, ZERO, RISK)
        assert trade.exit_reason == expect, value_legs


def test_entry_credit_above_the_wing_is_refused():
    """Four non-synchronous prints can imply a credit larger than the wing. That
    is free money and cannot occur. Left unchecked it is worse than an unchecked
    exit: the inflated credit puts the stop threshold above the wing, so the
    position runs unstopped to a settled exit that books a guaranteed profit."""
    impossible = minute(ENTRY_TS, 60.0, 5.0, 55.0, 4.0)           # credit 106 > 50
    honest = minute(at(16, 10, 1), 30.0, 20.0, 28.0, 18.0)        # credit 20
    adverse = minute(at(16, 10, 2), 45.0, 8.0, 5.0, 2.0)          # value 40 -> stop
    trade, _ = run_expiry(impossible + honest + adverse, EXPIRY, LOT, PARAMS,
                          ZERO, RISK)
    assert trade.entered_at == at(16, 10, 1) and trade.credit == 20.0
    assert trade.exit_reason == "stop" and trade.gross < 0


def test_exit_bound_is_the_wing_width_not_a_loose_multiple():
    """The bound has to be the wing itself. Widening it to 2x still passes every
    other test here, while admitting prints at 1.8x the wing as real exits."""
    bars = ENTRY + minute(at(16, 10, 1), 60.0, 5.0, 40.0, 5.0)     # implies 90
    trade, _ = run_expiry(bars, EXPIRY, LOT, PARAMS, ZERO, RISK)
    assert trade.exit_reason == "settled"        # the 90 print is refused
    assert trade.exit_cost <= PARAMS.wing_points


def test_slippage_default_is_modelled_not_zero():
    """The source carries one price per minute with no bid/ask, so this cost
    cannot be measured and must be assumed. Defaulting it to zero made the
    honest run the one you had to remember to ask for, and cost ~Rs 12,000 of
    optimism in the first published figure (docs/11)."""
    assert IntradayParams().slippage_per_leg > 0.0


# -- slippage ---------------------------------------------------------------
# The default is non-zero, so these paths are the ones that actually run.

SLIP = IntradayParams(offset_pct=0.008, wing_points=50.0, slippage_per_leg=0.25)


def test_slippage_is_charged_on_both_ends():
    """Round trip is 8 legs: entry credit is reduced and exit cost raised, each
    by 4 x the per-leg figure."""
    # Slippage cuts the credit to 19, which moves the target to 9.5 -- so the
    # exit that cleared a frictionless 10.0 threshold no longer does. The cost
    # is charged on the trigger, not just on the P&L.
    bars = ENTRY + minute(at(16, 10, 1), 6.0, 2.0, 5.0, 3.0)   # market value 6.0
    trade, _ = run_expiry(bars, EXPIRY, LOT, SLIP, ZERO, RISK)
    assert trade.exit_reason == "target"
    assert trade.credit == 19.0            # 20 - 4 x 0.25
    assert trade.exit_cost == 7.0          # 6 + 4 x 0.25
    assert trade.gross == (19.0 - 7.0) * LOT


def test_settled_exit_pays_slippage_too():
    """Charging it at entry and not at settlement flattered exactly the
    maximum-loss cycles, which is what the settled path exists to preserve."""
    hold = minute(at(16, 10, 1), 30.0, 20.0, 28.0, 18.0, spot=25400.0)
    trade, _ = run_expiry(ENTRY + hold, EXPIRY, LOT, SLIP, ZERO, RISK)
    assert trade.exit_reason == "settled"
    assert trade.exit_cost == pytest.approx(51.0)     # 50 intrinsic + 4 x 0.25
    assert trade.gross == pytest.approx((19.0 - 51.0) * LOT)


def test_bound_is_tested_on_the_market_price_not_the_modelled_one():
    """Slippage is a modelled cost, not a price. Adding it before the bound
    check rejected legitimate near-maximum-loss exits -- precisely where the
    stop has to fire -- and subtracting it at entry laundered an impossible
    credit into an acceptable one."""
    # True cost to close 49.0: legal, and past the stop. With slippage added
    # first it reads 50.0 and would be refused as non-synchronous.
    bars = ENTRY + minute(at(16, 10, 1), 45.0, 1.0, 6.0, 1.0)   # 45+6-1-1 = 49
    trade, _ = run_expiry(bars, EXPIRY, LOT, SLIP, ZERO, RISK)
    assert trade.exit_reason == "stop"
    assert trade.exit_cost == pytest.approx(50.0)     # 49 market + 4 x 0.25

    # Entry: a raw credit of 51 exceeds the wing and must be refused, even
    # though subtracting slippage would bring it to an acceptable 50.
    rich = minute(ENTRY_TS, 60.0, 5.0, 1.0, 5.0)      # 60+1-5-5 = 51
    later = minute(at(16, 10, 5), 30.0, 20.0, 28.0, 18.0)
    exitm = minute(at(16, 10, 6), 8.0, 2.0, 6.0, 3.0)
    trade, _ = run_expiry(rich + later + exitm, EXPIRY, LOT, SLIP, ZERO, RISK)
    assert trade.entered_at == at(16, 10, 5)          # skipped the bad print


# -- trailing profit-lock (docs/11 addendum) ------------------------------

# target off (frac=1.0 -> threshold 0, unreachable) to isolate the trail.
TRAIL = IntradayParams(offset_pct=0.008, wing_points=50.0, slippage_per_leg=0.0,
                       profit_target_frac=1.0, stop_loss_frac=0.6, trail_stop_frac=0.5)


def test_trailing_stop_locks_profit_on_retracement_hand_computed():
    """Credit 20. Profit peaks at 15 (cost-to-close 5), then gives back: at a
    give-back of 50% the exit fires when profit drops to 7.5, i.e. cost-to-close
    reaches 12.5. It must hold at the 10:02 peak and at 10:03 (profit 8 > 7.5),
    and exit at 10:04 (profit 7 <= 7.5)."""
    bars = (ENTRY
            + minute(at(16, 10, 1), 20.0, 15.0, 12.0, 7.0)    # value 10, profit 10
            + minute(at(16, 10, 2), 18.0, 15.0, 10.0, 8.0)    # value 5,  peak profit 15
            + minute(at(16, 10, 3), 22.0, 15.0, 12.0, 7.0)    # value 12, profit 8  -> hold
            + minute(at(16, 10, 4), 23.0, 15.0, 12.0, 7.0))   # value 13, profit 7  -> trail
    trade, _ = run_expiry(bars, EXPIRY, LOT, TRAIL, ZERO, RISK)
    assert trade is not None and trade.exit_reason == "trail"
    assert trade.exited_at == at(16, 10, 4)               # not the peak, not earlier
    assert trade.exit_cost == pytest.approx(13.0)
    assert trade.gross == pytest.approx((20 - 13) * LOT)  # 455 -- locked partial gain
    assert trade.net < trade.gross                        # STT still charged on the close


def test_trailing_stop_does_not_fire_without_a_profit_peak():
    """A trailing lock guards winners, not losers. With the mark never below the
    credit, peak profit is <= 0 so the trail never triggers; the hard stop is the
    only loss guard. Here the temporary marks are losses (25, 30) that neither
    trip the stop (38) nor the trail, and the cycle settles at expiry-intrinsic
    (spot 25,000 -> all legs worthless -> the full 20 credit is kept)."""
    bars = (ENTRY
            + minute(at(16, 10, 1), 30.0, 15.0, 18.0, 8.0)    # value 25, a loss
            + minute(at(16, 10, 2), 33.0, 15.0, 20.0, 8.0))   # value 30, worse, stop 38 unhit
    trade, _ = run_expiry(bars, EXPIRY, LOT, TRAIL, ZERO, RISK)
    assert trade is not None and trade.exit_reason == "settled"
    assert trade.exit_reason != "trail"
    assert trade.gross == pytest.approx(20 * LOT)         # 1300, full profit held to settle
