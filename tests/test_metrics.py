from datetime import date

import pytest

from optionsbot.metrics import BacktestReport, max_drawdown


def test_max_drawdown_hand_computed():
    # Peaks: 100, 120, 120, 130, 130 -> deepest trough 130 - 90 = 40
    assert max_drawdown([100, 120, 110, 130, 90]) == 40


def test_max_drawdown_monotonic_rise_is_zero():
    assert max_drawdown([100, 105, 110]) == 0.0


def test_report_properties():
    r = BacktestReport(start_capital=100000.0)
    r.equity_curve = [(date(2026, 7, 7), 99000.0), (date(2026, 7, 8), 101000.0)]
    r.trade_pnls = [1500.0, -500.0]
    r.total_costs = 250.0
    assert r.end_equity == 101000.0
    assert r.net_pnl == pytest.approx(1000.0)
    assert r.net_return_pct == pytest.approx(1.0)
    assert r.max_drawdown_rupees == pytest.approx(1000.0)  # start capital is the first peak
    assert r.cost_drag_pct == pytest.approx(0.25)
    assert r.worst_trade == -500.0
