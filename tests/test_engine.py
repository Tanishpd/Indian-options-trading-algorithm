"""Gate 2a (docs/06) plus engine risk-enforcement behavior. Every expected
value is a hand-computed literal — never derived from the code under test.

Gate-2a fixture: lot 65, brokerage Rs 20/order, STT 0.15% on sells, all
other charge rates zeroed.

  Entry (2026-07-07): sell 25900CE @60, buy 26100CE @25, sell 25100PE @55, buy 24900PE @22
    cash: +3900 - 1625 + 3575 - 1430          = +4420.00
    costs: 4 x 20 + STT (5.85 + 5.3625)       =    91.2125
  Exit  (2026-07-08): buy back @10 / @8, sell wings @2 / @1.5
    cash: -650 + 130 - 520 + 97.5             =  -942.50
    costs: 4 x 20 + STT (0.195 + 0.14625)     =    80.34125
  Net P&L = (4420 - 942.5) - 171.55375        = +3305.94625
"""
import pytest

from conftest import D1, D2, D3, D4, flat_bar, leg, make_cfg, ohlc_bar
from optionsbot.backtest.data import by_day
from optionsbot.backtest.engine import BacktestEngine, EngineError, Order
from optionsbot.instruments import Right, Side


class CondorRoundTrip:
    def decide(self, ctx):
        if ctx.day == D1:
            return [
                Order(leg(25900, Right.CALL, Side.SELL), 60.0),
                Order(leg(26100, Right.CALL, Side.BUY), 25.0),
                Order(leg(25100, Right.PUT, Side.SELL), 55.0),
                Order(leg(24900, Right.PUT, Side.BUY), 22.0),
            ]
        if ctx.day == D2:
            return [
                Order(leg(25900, Right.CALL, Side.BUY), 10.0),
                Order(leg(26100, Right.CALL, Side.SELL), 2.0),
                Order(leg(25100, Right.PUT, Side.BUY), 8.0),
                Order(leg(24900, Right.PUT, Side.SELL), 1.5),
            ]
        return []


def condor_data():
    day1 = [
        flat_bar(D1, 25900, Right.CALL, 60.0), flat_bar(D1, 26100, Right.CALL, 25.0),
        flat_bar(D1, 25100, Right.PUT, 55.0), flat_bar(D1, 24900, Right.PUT, 22.0),
    ]
    day2 = [
        flat_bar(D2, 25900, Right.CALL, 10.0), flat_bar(D2, 26100, Right.CALL, 2.0),
        flat_bar(D2, 25100, Right.PUT, 8.0), flat_bar(D2, 24900, Right.PUT, 1.5),
    ]
    return by_day(day1 + day2)


def test_gate_2a_condor_round_trip_hand_computed():
    report = BacktestEngine(make_cfg(), CondorRoundTrip()).run(condor_data())

    assert not report.halted
    assert report.total_costs == pytest.approx(171.55375, abs=1e-9)
    assert report.net_pnl == pytest.approx(3305.94625, abs=1e-9)

    curve = dict(report.equity_curve)
    assert curve[D1] == pytest.approx(99908.7875, abs=1e-9)   # only costs lost while open
    assert curve[D2] == pytest.approx(103305.94625, abs=1e-9)

    assert len(report.trade_pnls) == 4
    assert sum(report.trade_pnls) == pytest.approx(3305.94625, abs=1e-9)
    assert report.max_drawdown_rupees == pytest.approx(91.2125, abs=1e-9)
    assert report.open_positions_end == 0


class BuyAndCollapse:
    """Buys one option; the price path trips the kill-switch."""

    def decide(self, ctx):
        if ctx.day == D1:
            return [Order(leg(25900, Right.CALL, Side.BUY), 100.0)]
        return []


def test_kill_switch_halts_and_flattens_next_day():
    data = by_day([
        flat_bar(D1, 25900, Right.CALL, 100.0),
        flat_bar(D2, 25900, Right.CALL, 10.0),
        flat_bar(D3, 25900, Right.CALL, 10.0),
    ])
    cfg = make_cfg(max_dd=5000.0, daily=50000.0)
    report = BacktestEngine(cfg, BuyAndCollapse()).run(data)

    assert report.halted
    assert "max drawdown" in report.halt_reason
    # Day1: 100000 - 6500 - 20 = 93480 cash + 6500 value = 99980 equity.
    # Day2 close 10: equity = 93480 + 650 = 94130 -> dd 5870 from seeded 100000 peak.
    # Day3 flatten: sell 65 @ 10 (band 0) -> +650 - 20 - STT 0.975 = +629.025.
    curve = dict(report.equity_curve)
    assert curve[D1] == pytest.approx(99980.0)
    assert curve[D2] == pytest.approx(94130.0)
    assert curve[D3] == pytest.approx(94109.025, abs=1e-9)
    assert len(report.trade_pnls) == 1
    # (10 - 100) * 65 = -5850 gross, minus entry 20 and exit 20.975 costs.
    assert report.trade_pnls[0] == pytest.approx(-5890.975, abs=1e-9)
    assert report.open_positions_end == 0


def test_day_one_loss_trips_seeded_switch():
    # Intraday collapse on the very first day: buy at 100, close at 5.
    # Equity D1 = 100000 - 6500 - 20 + 325 = 93805 -> dd 6195 from START capital.
    data = by_day([
        ohlc_bar(D1, 25900, Right.CALL, 100.0, 100.0, 5.0, 5.0),
        flat_bar(D2, 25900, Right.CALL, 5.0),
    ])
    report = BacktestEngine(make_cfg(max_dd=5000.0, daily=50000.0), BuyAndCollapse()).run(data)

    assert report.halted
    assert "max drawdown" in report.halt_reason
    assert dict(report.equity_curve)[D1] == pytest.approx(93805.0)
    assert report.open_positions_end == 0  # flattened on D2


class NakedSeller:
    def decide(self, ctx):
        if ctx.day == D1:
            return [Order(leg(25900, Right.CALL, Side.SELL), 60.0)]
        return []


def test_naked_book_trips_kill_switch():
    data = by_day([
        flat_bar(D1, 25900, Right.CALL, 60.0),
        flat_bar(D2, 25900, Right.CALL, 60.0),
    ])
    cfg = make_cfg(max_dd=50000.0, daily=50000.0)
    report = BacktestEngine(cfg, NakedSeller()).run(data)

    assert report.halted
    assert "naked short" in report.halt_reason
    assert report.open_positions_end == 0  # bought back on D2


def test_book_worst_case_above_per_trade_cap_trips():
    # 200-wide condor, net credit 68/share -> worst case (200-68)*65 = Rs 8,580.
    cfg = make_cfg(max_dd=50000.0, daily=50000.0, per_trade=2000.0)
    report = BacktestEngine(cfg, CondorRoundTrip()).run(condor_data())

    assert report.halted
    assert "per-trade cap" in report.halt_reason
    # Honest flatten: shorts buy back (limit above market fills), but the
    # collapsed long wings gap below their sell bands and stay open — the
    # report says so instead of fabricating exits.
    assert report.unfilled_orders == 2
    assert report.open_positions_end == 2


def test_position_past_expiry_raises():
    expiry_d1 = D1

    class HoldThroughExpiry:
        def decide(self, ctx):
            if ctx.day == D1:
                return [Order(leg(25900, Right.CALL, Side.BUY, expiry=expiry_d1), 60.0)]
            return []

    data = {
        D1: {b.key: b for b in [flat_bar(D1, 25900, Right.CALL, 60.0, expiry=expiry_d1)]},
        D2: {},
    }
    with pytest.raises(EngineError, match="past its .* expiry"):
        BacktestEngine(make_cfg(), HoldThroughExpiry()).run(data)


def test_flatten_respects_gaps_and_retries():
    # D2 trips the switch; D3 gaps below the sell band (no fill); D4 fills.
    data = by_day([
        flat_bar(D1, 25900, Right.CALL, 100.0),
        flat_bar(D2, 25900, Right.CALL, 10.0),
        flat_bar(D3, 25900, Right.CALL, 3.0),   # limit 10*0.95=9.5 > high 3 -> unfilled
        flat_bar(D4, 25900, Right.CALL, 3.0),   # limit 3*0.95=2.85 <= high 3 -> fills
    ])
    cfg = make_cfg(max_dd=5000.0, daily=50000.0, band=0.05)
    report = BacktestEngine(cfg, BuyAndCollapse()).run(data)

    assert report.halted
    assert report.unfilled_orders >= 1          # the D3 gap
    assert report.open_positions_end == 0       # eventually exited on D4
    assert len(report.trade_pnls) == 1
    assert D4 in dict(report.equity_curve)


def test_strategy_cannot_mutate_engine_state():
    class Mutator:
        def decide(self, ctx):
            if ctx.positions:
                ctx.positions[0].shares = 1     # frozen -> raises
            if ctx.day == D1:
                return [Order(leg(25900, Right.CALL, Side.BUY), 100.0)]
            return []

    data = by_day([
        flat_bar(D1, 25900, Right.CALL, 100.0),
        flat_bar(D2, 25900, Right.CALL, 100.0),
    ])
    import dataclasses
    with pytest.raises(dataclasses.FrozenInstanceError):
        BacktestEngine(make_cfg(max_dd=50000.0, daily=50000.0), Mutator()).run(data)


def test_partial_close_raises_before_mutating_report():
    class PartialCloser:
        def decide(self, ctx):
            if ctx.day == D1:
                return [Order(leg(25900, Right.CALL, Side.BUY, lots=2), 100.0)]
            return [Order(leg(25900, Right.CALL, Side.SELL, lots=1), 100.0)]

    data = by_day([
        flat_bar(D1, 25900, Right.CALL, 100.0),
        flat_bar(D2, 25900, Right.CALL, 100.0),
    ])
    engine = BacktestEngine(make_cfg(max_dd=500000.0, daily=500000.0, per_trade=500000.0), PartialCloser())
    with pytest.raises(EngineError, match="partial closes"):
        engine.run(data)


def test_unfilled_orders_leave_state_unchanged():
    data = by_day([flat_bar(D1, 25900, Right.CALL, 100.0)])

    class LowballBuyer:
        def decide(self, ctx):
            if ctx.day == D1:
                return [Order(leg(25900, Right.CALL, Side.BUY), 50.0)]  # below the bar's low
            return []

    report = BacktestEngine(make_cfg(), LowballBuyer()).run(data)
    assert report.total_costs == 0.0
    assert report.unfilled_orders == 1
    assert dict(report.equity_curve)[D1] == pytest.approx(100000.0)
