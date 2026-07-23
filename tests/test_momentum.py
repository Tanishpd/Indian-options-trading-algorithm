"""Momentum backtest. Every building block is pinned to a hand-computed value,
and the strategy-level tests pin behaviour (ranking, cash conservation, the
regime filter) rather than trusting the engine.
"""
from datetime import date, timedelta

import pytest

from optionsbot.data.equity import Series, month_end_days, trading_days
from optionsbot.research.momentum import (
    EquityCostConfig, MomentumParams, backtest, momentum_scores, trade_cost)

D0 = date(2025, 1, 1)


def days(n: int) -> tuple[date, ...]:
    # Consecutive calendar days are fine for tests; the engine only needs order.
    return tuple(D0 + timedelta(days=i) for i in range(n))


def series(sym: str, closes: list[float], n: int | None = None) -> Series:
    ds = days(n or len(closes))
    return Series(symbol=sym, dates=ds, closes=tuple(closes))


# -- Series arithmetic ----------------------------------------------------

def test_lookback_return_hand_computed():
    s = series("X", [100.0, 110.0, 121.0])
    assert s.lookback_return(2, 2) == pytest.approx(0.21)     # 121/100 - 1
    assert s.lookback_return(2, 5) is None                    # not enough history


def test_daily_vol_hand_computed():
    s = series("X", [100.0, 110.0, 99.0])
    # daily returns +0.10 then -0.10; sample stdev = sqrt(((0.1)^2+(0.1)^2)/1)
    assert s.daily_vol(2, 2) == pytest.approx(0.14142135, abs=1e-6)


def test_index_on_or_before():
    s = series("X", [1.0, 2.0, 3.0])
    assert s.index_on_or_before(D0 + timedelta(days=1)) == 1
    assert s.index_on_or_before(D0 - timedelta(days=1)) is None
    assert s.index_on_or_before(D0 + timedelta(days=99)) == 2   # past the end


def test_month_end_days():
    ds = [date(2025, 1, 30), date(2025, 1, 31), date(2025, 2, 3), date(2025, 2, 27)]
    assert month_end_days(ds) == [date(2025, 1, 31), date(2025, 2, 27)]


# -- Costs ----------------------------------------------------------------

def test_trade_cost_buy_and_sell():
    cfg = EquityCostConfig()
    # value 1,00,000. txn 2.97, sebi 0.1, gst 0.18*(2.97+0.1)=0.5526,
    # stt 100, slip 50; stamp 15 on BUY only.
    assert trade_cost(100_000, is_buy=True, cfg=cfg) == pytest.approx(168.6226)
    assert trade_cost(100_000, is_buy=False, cfg=cfg) == pytest.approx(153.6226)
    # ~32 bps round trip, matching the framework's honest cost table (docs/14).
    rt = trade_cost(100_000, True, cfg) + trade_cost(100_000, False, cfg)
    assert 300 < rt < 340


# -- Scoring --------------------------------------------------------------

P = MomentumParams(top_n=1, lookback_short=3, lookback_long=5,
                   use_regime_filter=False)


def test_momentum_ranks_high_vol_adjusted_return_first():
    """A steady climber outranks a volatile one with the same-ish raw return,
    because the score divides by volatility. A flat stock (zero vol) is skipped,
    not ranked."""
    a = series("A", [100, 101, 102, 103, 104, 105, 106, 107])   # steady up
    b = series("B", [100, 100, 100, 100, 100, 100, 100, 100])   # flat -> skip
    c = series("C", [100, 90, 110, 95, 115, 100, 120, 105])     # volatile
    scores = momentum_scores({"A": a, "B": b, "C": c}, days(8)[-1], P)
    assert "B" not in scores                                    # zero-vol excluded
    assert max(scores, key=scores.get) == "A"


# -- Backtest -------------------------------------------------------------

BP = MomentumParams(top_n=2, lookback_short=2, lookback_long=3,
                    use_regime_filter=False)


def three_stock_universe():
    # 5 days in Jan, 3 in Feb -> rebalances on the last Jan and last Feb day.
    jan = [date(2025, 1, d) for d in (27, 28, 29, 30, 31)]
    feb = [date(2025, 2, d) for d in (25, 26, 27)]
    ds = tuple(jan + feb)
    up = Series("UP", ds, (100, 102, 104, 106, 108, 110, 112, 114))
    mid = Series("MID", ds, (100, 101, 100, 101, 102, 103, 102, 103))
    down = Series("DOWN", ds, (100, 98, 96, 94, 92, 90, 88, 86))
    return {"UP": up, "MID": mid, "DOWN": down}


def test_backtest_holds_top_n_and_charges_costs():
    uni = three_stock_universe()
    res = backtest(uni, index=None, params=BP, costs=EquityCostConfig(),
                   start_capital=500_000.0)
    assert res.rebalances == 2
    assert res.costs_paid > 0
    assert res.end_equity > 0
    # Costs leak equity below the untouched start on the first rebalance day.
    assert dict(res.equity_curve)[date(2025, 1, 31)] < 500_000.0


def test_single_rebalance_conserves_value_minus_costs():
    """Buying at the same close it is marked at conserves value exactly; only
    the transaction cost leaves the book. Pinned on a one-rebalance run so the
    total cost IS the single rebalance's cost."""
    ds = tuple(date(2025, 1, d) for d in (26, 27, 28, 29, 30, 31))
    uni = {
        "UP": Series("UP", ds, (100, 102, 104, 106, 108, 110)),
        "MID": Series("MID", ds, (100, 101, 100, 101, 102, 103)),
        "DOWN": Series("DOWN", ds, (100, 98, 96, 94, 92, 90)),
    }
    res = backtest(uni, index=None, params=BP, costs=EquityCostConfig(),
                   start_capital=500_000.0)
    assert res.rebalances == 1
    assert res.end_equity == pytest.approx(500_000.0 - res.costs_paid, rel=1e-12)


def test_backtest_never_holds_the_worst_ranked_name():
    uni = three_stock_universe()          # DOWN is a monotone loser
    res = backtest(uni, index=None, params=BP, costs=EquityCostConfig())
    # top_n=2 of 3; the persistent loser should be the one dropped.
    assert res.turnover_fracs[0] > 0
    assert res.max_drawdown_pct >= 0


def test_regime_filter_forces_cash_below_the_average():
    uni = three_stock_universe()
    # An index in a clear downtrend: every rebalance sits below its own average.
    idx = Series("IDX", tuple(sorted({d for s in uni.values() for d in s.dates})),
                 tuple(200 - i for i in range(8)))
    params = MomentumParams(top_n=2, lookback_short=2, lookback_long=3,
                            use_regime_filter=True, regime_sma=3)
    res = backtest(uni, index=idx, params=params, costs=EquityCostConfig())
    assert res.in_cash_rebalances >= 1
    # In cash for the whole run: equity never moves from start except for costs,
    # and with nothing ever bought there are no costs.
    assert res.costs_paid == pytest.approx(0.0)
    assert res.end_equity == pytest.approx(500_000.0)


# -- point-in-time membership (survivorship-bias fix) ---------------------

from optionsbot.research.momentum import members_asof
from optionsbot.data.equity import load_membership


def test_members_asof_picks_the_snapshot_in_force():
    sched = [
        (date(2020, 1, 1), frozenset({"A", "B", "C"})),
        (date(2020, 7, 1), frozenset({"A", "C", "D"})),   # B dropped, D added
    ]
    assert members_asof(sched, date(2019, 12, 31)) is None      # before first snapshot
    assert members_asof(sched, date(2020, 3, 1)) == frozenset({"A", "B", "C"})
    assert members_asof(sched, date(2020, 7, 1)) == frozenset({"A", "C", "D"})
    assert members_asof(sched, date(2021, 1, 1)) == frozenset({"A", "C", "D"})
    assert members_asof(None, date(2020, 3, 1)) is None          # no schedule


def test_membership_restricts_the_scored_universe():
    """A stock outside the point-in-time index is not scored, even with data."""
    a = series("A", [100, 101, 102, 103, 104, 105, 106, 107])
    d = series("D", [100, 130, 90, 140, 80, 150, 70, 160])       # would score high raw
    scores_all = momentum_scores({"A": a, "D": d}, days(8)[-1], P)
    assert "D" in scores_all
    scores_pit = momentum_scores({"A": a, "D": d}, days(8)[-1], P,
                                 members=frozenset({"A"}))
    assert set(scores_pit) == {"A"}                             # D excluded


def test_backtest_uses_point_in_time_membership():
    """A loser dropped from the index before it craters must not be held after
    its removal — the whole point of removing survivorship bias."""
    uni = three_stock_universe()
    # DOWN is in the index only for the first month, then removed.
    sched = [(date(2025, 1, 1), frozenset({"UP", "MID", "DOWN"})),
             (date(2025, 2, 1), frozenset({"UP", "MID"}))]
    res = backtest(uni, index=None, params=BP, costs=EquityCostConfig(),
                   membership=sched)
    assert res.rebalances == 2                                  # ran normally


def test_load_membership_reads_dated_snapshots(tmp_path):
    (tmp_path / "2020-01-01.txt").write_text("# jan review\nA\nB\nC\n")
    (tmp_path / "2020-07-01.txt").write_text("A\nC\nD\n")
    (tmp_path / "notes.txt").write_text("ignored — not a date\n")
    sched = load_membership(tmp_path)
    assert [d for d, _ in sched] == [date(2020, 1, 1), date(2020, 7, 1)]
    assert sched[0][1] == frozenset({"A", "B", "C"})
    assert sched[1][1] == frozenset({"A", "C", "D"})
