"""Hold-to-expiry study. Expected P&L values are hand-computed literals."""
from datetime import date

import pytest

from optionsbot.config import CostConfig, RiskConfig
from optionsbot.data.bhavcopy import EodRow
from optionsbot.instruments import Right
from optionsbot.research.hold_to_expiry import CondorParams, run

EXPIRY = date(2026, 7, 21)
ENTRY = date(2026, 7, 15)
ZERO = CostConfig(brokerage_per_order=0, txn_charge_rate=0, sebi_fee_rate=0,
                  stamp_duty_rate=0, gst_rate=0)
RISK = RiskConfig(per_trade_max_loss_rupees=2000.0)


def row(day, strike, right, price, underlying=25000.0, lot=65):
    return EodRow(day=day, index="NIFTY", expiry=EXPIRY, strike=strike, right=right,
                  open=price, high=price, low=price, close=price, last_price=price,
                  settlement=price, underlying=underlying, volume=100,
                  open_interest=100, lot_size=lot)


def book(entry_prices, exit_prices, spot=25000.0, exit_spot=25000.0):
    """entry/exit prices keyed (strike, right)."""
    days = {}
    for day, prices, und in ((ENTRY, entry_prices, spot), (EXPIRY, exit_prices, exit_spot)):
        days[day] = [row(day, k, r, p, underlying=und) for (k, r), p in prices.items()]
    # entry_days_before=4 counts back from expiry, so ENTRY must be the 4th
    # trading day from the end: three filler sessions sit between it and expiry.
    for d in (date(2026, 7, 16), date(2026, 7, 17), date(2026, 7, 20)):
        days[d] = [row(d, 25200.0, Right.CALL, 1.0, underlying=spot)]
    return days


SC, LC, SP, LP = 25200.0, 25250.0, 24800.0, 24750.0


def test_profitable_cycle_hand_computed():
    # credit = 30 + 28 - 12 - 10 = 36/share; exit costs 6 + 5 - 1 - 1 = 9/share
    # gross = (36 - 9) * 65 = Rs 1,755, zero costs configured
    days = book(
        {(SC, Right.CALL): 30.0, (LC, Right.CALL): 12.0,
         (SP, Right.PUT): 28.0, (LP, Right.PUT): 10.0},
        {(SC, Right.CALL): 6.0, (LC, Right.CALL): 1.0,
         (SP, Right.PUT): 5.0, (LP, Right.PUT): 1.0},
    )
    s = run(days, CondorParams(offset_pct=0.008, wing_points=50.0), ZERO, RISK)
    assert len(s.trades) == 1
    t = s.trades[0]
    assert t.credit == 36.0 and t.exit_cost == 9.0
    assert t.gross == 1755.0
    # STT is statutory and deliberately not configurable, so it survives a
    # zeroed CostConfig: 0.15% on the two entry sells (turnover 3,770) plus the
    # two wing sells at exit (turnover 130) = Rs 5.85.
    assert t.costs == pytest.approx(5.85)
    assert t.net == pytest.approx(1749.15) and t.won
    assert s.win_rate == 100.0


def test_costs_are_subtracted():
    days = book(
        {(SC, Right.CALL): 30.0, (LC, Right.CALL): 12.0,
         (SP, Right.PUT): 28.0, (LP, Right.PUT): 10.0},
        {(SC, Right.CALL): 6.0, (LC, Right.CALL): 1.0,
         (SP, Right.PUT): 5.0, (LP, Right.PUT): 1.0},
    )
    s = run(days, CondorParams(offset_pct=0.008, wing_points=50.0), CostConfig(), RISK)
    t = s.trades[0]
    assert t.gross == 1755.0
    assert t.costs > 150.0                    # 8 fills, Rs 20 brokerage each plus taxes
    assert t.net == t.gross - t.costs


def test_cycle_over_the_per_trade_cap_is_skipped():
    # credit only 6/share on a 50-pt wing -> worst case (50-6)*65 = Rs 2,860 > cap
    days = book(
        {(SC, Right.CALL): 5.0, (LC, Right.CALL): 3.0,
         (SP, Right.PUT): 6.0, (LP, Right.PUT): 2.0},
        {(SC, Right.CALL): 1.0, (LC, Right.CALL): 0.5,
         (SP, Right.PUT): 1.0, (LP, Right.PUT): 0.5},
    )
    s = run(days, CondorParams(offset_pct=0.008, wing_points=50.0), ZERO, RISK)
    assert s.trades == [] and s.skipped["over_cap"] == 1


def test_missing_leg_skips_rather_than_invents_a_fill():
    days = book(
        {(SC, Right.CALL): 30.0, (SP, Right.PUT): 28.0, (LP, Right.PUT): 10.0},
        {(SC, Right.CALL): 6.0, (LC, Right.CALL): 1.0,
         (SP, Right.PUT): 5.0, (LP, Right.PUT): 1.0},
    )
    s = run(days, CondorParams(offset_pct=0.008, wing_points=50.0), ZERO, RISK)
    assert s.trades == [] and s.skipped["missing_legs"] == 1


def test_drawdown_tracks_the_trade_sequence():
    from optionsbot.research.hold_to_expiry import Study, Trade

    def t(net):
        return Trade(expiry=EXPIRY, entry_day=ENTRY, spot_at_entry=1.0, spot_at_exit=1.0,
                     short_call=1.0, short_put=1.0, credit=1.0, exit_cost=0.0,
                     lot_size=65, costs=0.0, gross=net, net=net)

    s = Study(trades=[t(1000), t(-3000), t(500)], skipped={})
    assert s.net == -1500
    assert s.max_drawdown(100000) == 3000     # peak 101,000 -> trough 98,000


def sensex_row(day, strike, right, price, underlying=80000.0, lot=20, expiry=EXPIRY):
    return EodRow(day=day, index="SENSEX", expiry=expiry, strike=strike, right=right,
                  open=price, high=price, low=price, close=price, last_price=price,
                  settlement=price, underlying=underlying, volume=100,
                  open_interest=100, lot_size=lot)


def test_works_on_sensex_not_just_nifty():
    """The index must come from the data. Hard-coding NIFTY made every SENSEX
    cycle skip as missing_legs — a wrong answer that looked like thin data."""
    sc, sp = 80600.0, 79400.0
    days = {}
    for day, prices in (
        (ENTRY, {(sc, Right.CALL): 30.0, (sc + 200, Right.CALL): 12.0,
                 (sp, Right.PUT): 28.0, (sp - 200, Right.PUT): 10.0}),
        (EXPIRY, {(sc, Right.CALL): 6.0, (sc + 200, Right.CALL): 1.0,
                  (sp, Right.PUT): 5.0, (sp - 200, Right.PUT): 1.0}),
    ):
        days[day] = [sensex_row(day, k, r, p) for (k, r), p in prices.items()]
    for d in (date(2026, 7, 16), date(2026, 7, 17), date(2026, 7, 20)):
        days[d] = [sensex_row(d, sc, Right.CALL, 1.0)]

    s = run(days, CondorParams(offset_pct=0.0075, wing_points=200.0, strike_step=100.0),
            ZERO, RiskConfig(per_trade_max_loss_rupees=5000.0))
    assert len(s.trades) == 1
    assert s.trades[0].lot_size == 20              # SENSEX lot, read from the data
    assert s.trades[0].credit == 36.0


def test_untraded_leg_is_skipped_not_crashed():
    """traded_only=False rows carry last_traded=None; arithmetic on them raised
    TypeError before this guard."""
    days = book(
        {(SC, Right.CALL): 30.0, (LC, Right.CALL): 12.0,
         (SP, Right.PUT): 28.0, (LP, Right.PUT): 10.0},
        {(SC, Right.CALL): 6.0, (LC, Right.CALL): 1.0,
         (SP, Right.PUT): 5.0, (LP, Right.PUT): 1.0},
    )
    # make one entry leg untraded, as fetch_day(traded_only=False) would
    from dataclasses import replace
    days[ENTRY] = [replace(r, volume=0) if r.strike == LC else r for r in days[ENTRY]]
    s = run(days, CondorParams(offset_pct=0.008, wing_points=50.0), ZERO, RISK)
    assert s.trades == [] and s.skipped["untraded_leg"] == 1


def test_mixed_indices_refused():
    days = {
        ENTRY: [row(ENTRY, SC, Right.CALL, 30.0),
                sensex_row(ENTRY, 80600.0, Right.CALL, 30.0)],
    }
    with pytest.raises(ValueError, match="mixes indices"):
        run(days, CondorParams(), ZERO, RISK)
