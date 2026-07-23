"""Strategy-search engine tests.

The load-bearing test is `test_base_config_reproduces_momentum_backtest`: the
generalised engine must return the SAME equity curve as the pinned base backtest
when its config is the default. If it drifts, every overlay comparison is against
a different base and the whole search is meaningless. The STCG accounting is
pinned to a hand-computed rupee figure.
"""
from dataclasses import replace
from datetime import date, timedelta

import pytest

from optionsbot.data.equity import Series
from optionsbot.research.momentum import EquityCostConfig, MomentumParams, backtest
from optionsbot.research.strategy_search import (
    StrategyConfig, run_strategy, _voltarget_scale, _residual_pair,
    _index_returns_by_date)

D0 = date(2025, 1, 1)


def days(n: int) -> tuple[date, ...]:
    return tuple(D0 + timedelta(days=i) for i in range(n))


def three_stock_universe() -> dict[str, Series]:
    jan = [date(2025, 1, d) for d in (27, 28, 29, 30, 31)]
    feb = [date(2025, 2, d) for d in (25, 26, 27)]
    ds = tuple(jan + feb)
    return {
        "UP": Series("UP", ds, (100, 102, 104, 106, 108, 110, 112, 114)),
        "MID": Series("MID", ds, (100, 101, 100, 101, 102, 103, 102, 103)),
        "DOWN": Series("DOWN", ds, (100, 98, 96, 94, 92, 90, 88, 86)),
    }


def _curves_equal(a, b, tol=1e-9):
    assert [d for d, _ in a] == [d for d, _ in b]
    for (_, va), (_, vb) in zip(a, b):
        assert va == pytest.approx(vb, abs=tol)


# -- the reproduction invariant -------------------------------------------

def test_base_config_reproduces_momentum_backtest():
    """Default config, no regime: identical to momentum.backtest."""
    uni = three_stock_universe()
    mp = MomentumParams(top_n=2, lookback_short=2, lookback_long=3,
                        use_regime_filter=False)
    cfg = StrategyConfig(name="base", top_n=2, lookback_short=2, lookback_long=3,
                         regime_mode="none")
    ref = backtest(uni, index=None, params=mp, costs=EquityCostConfig())
    got = run_strategy(uni, index=None, cfg=cfg, costs=EquityCostConfig())
    _curves_equal(got.equity_curve, ref.equity_curve)
    assert got.costs_paid == pytest.approx(ref.costs_paid)


def test_base_config_reproduces_regime_filter():
    """price_sma regime must match momentum's _regime_ok bar-for-bar."""
    uni = three_stock_universe()
    idx = Series("IDX", tuple(sorted({d for s in uni.values() for d in s.dates})),
                 tuple(200 - i for i in range(8)))          # clear downtrend
    mp = MomentumParams(top_n=2, lookback_short=2, lookback_long=3,
                        use_regime_filter=True, regime_sma=3)
    cfg = StrategyConfig(name="base", top_n=2, lookback_short=2, lookback_long=3,
                         regime_mode="price_sma", regime_sma=3)
    ref = backtest(uni, index=idx, params=mp, costs=EquityCostConfig())
    got = run_strategy(uni, index=idx, cfg=cfg, costs=EquityCostConfig())
    _curves_equal(got.equity_curve, ref.equity_curve)
    assert got.in_cash_rebalances == ref.in_cash_rebalances


# -- STCG tax accounting (hand computed) ----------------------------------

FREE = EquityCostConfig(brokerage_per_order=0.0, stt_rate=0.0, txn_rate=0.0,
                        sebi_rate=0.0, stamp_rate=0.0, gst_rate=0.0,
                        slippage_rate=0.0)


def _rotation_universe():
    """A is held Jan, forced out in Feb by membership; B held Feb. Zero costs, so
    the only leakage is tax."""
    jan = [date(2025, 1, d) for d in (27, 28, 29, 30, 31)]
    feb = [date(2025, 2, d) for d in (25, 26, 27)]
    ds = tuple(jan + feb)
    uni = {
        "A": Series("A", ds, (96, 98, 100, 99, 100, 105, 110, 120)),   # 100 -> 120
        "B": Series("B", ds, (100, 101, 102, 103, 104, 106, 108, 110)),
    }
    sched = [(date(2025, 1, 1), frozenset({"A"})),
             (date(2025, 2, 1), frozenset({"B"}))]
    return uni, sched


def test_stcg_taxes_realised_gain_hand_computed():
    uni, sched = _rotation_universe()
    cfg = StrategyConfig(name="tax", top_n=1, lookback_short=2, lookback_long=3,
                         regime_mode="none", apply_stcg=True, stcg_rate=0.20)
    res = run_strategy(uni, index=None, cfg=cfg, costs=FREE,
                       start_capital=500_000.0, membership=sched)
    # Buy 5,000 shares of A at 100 (₹5,00,000), sell at 120 -> gain ₹1,00,000.
    # STCG at 20% = ₹20,000. Portfolio was worth ₹6,00,000 pre-tax.
    assert res.tax_paid == pytest.approx(20_000.0)
    assert res.end_equity == pytest.approx(580_000.0)


def test_no_sale_means_no_tax():
    """Same config, tax off: the ₹20k stays in the book."""
    uni, sched = _rotation_universe()
    cfg = StrategyConfig(name="notax", top_n=1, lookback_short=2, lookback_long=3,
                         regime_mode="none", apply_stcg=False)
    res = run_strategy(uni, index=None, cfg=cfg, costs=FREE,
                       start_capital=500_000.0, membership=sched)
    assert res.tax_paid == 0.0
    assert res.end_equity == pytest.approx(600_000.0)


# -- exposure scaling ------------------------------------------------------

def test_voltarget_scale_clips_to_floor_and_cap():
    # An index whipsawing +/-10% daily has very high realized vol -> target/rv is
    # tiny -> exposure pinned to the floor.
    idx = Series("IDX", days(80),
                 tuple(100 * (1.1 if i % 2 else 1.0) for i in range(80)))
    cfg = StrategyConfig(name="vt", exposure_mode="vol_target", target_vol=0.15,
                         vol_lookback=63, exposure_floor=0.3, exposure_cap=1.0)
    scale = _voltarget_scale(idx, days(80)[-1], cfg)
    assert scale == pytest.approx(0.3)                     # floored
    # Binary config (default) never scales.
    base = StrategyConfig(name="b")
    assert _voltarget_scale(idx, days(80)[-1], base) == 1.0


# -- residual momentum must measure idiosyncratic drift, not zero it --------

def test_residual_pair_captures_idiosyncratic_drift():
    """A stock that beats the index by a steady margin (positive alpha, same beta)
    must get a clearly positive residual-momentum score; an index tracker (~zero
    alpha) must score near zero. Regression guard for the OLS-alpha bug that
    forced residual means to zero and turned the ranking into noise."""
    n = 60
    # market returns (varied), plus idiosyncratic noise on a different cycle so
    # both stocks have residual variance (a zero-variance residual is undefined).
    rm = [0.0] + [0.010 if k % 2 == 0 else -0.004 for k in range(1, n)]
    noise = [0.0] + [(0.003, -0.001, -0.002)[k % 3] for k in range(1, n)]

    def build(*, market_only: bool, drift: float = 0.0) -> tuple[float, ...]:
        c = [100.0]
        for k in range(1, n):
            r = rm[k] if market_only else rm[k] + noise[k] + drift
            c.append(c[-1] * (1 + r))
        return tuple(c)

    ds = days(n)
    idx = Series("IDX", ds, build(market_only=True))
    track = Series("TRACK", ds, build(market_only=False, drift=0.0))    # ~zero alpha
    alpha = Series("ALPHA", ds, build(market_only=False, drift=0.004))  # +40bps/day drift
    cfg = StrategyConfig(name="r", rank_mode="residual",
                         lookback_short=20, lookback_long=40, regime_mode="none")
    idx_ret = _index_returns_by_date(idx)
    i = alpha.index_on_or_before(ds[-1])
    a_pair = _residual_pair(alpha, i, cfg, idx_ret)
    t_pair = _residual_pair(track, i, cfg, idx_ret)
    assert a_pair is not None and t_pair is not None
    assert a_pair[0] > 0.5 and a_pair[1] > 0.5    # drift shows up (was ~0 when buggy)
    assert abs(t_pair[0]) < 0.5                    # tracker has no drift


# -- trailing stop (intra-month exit) -------------------------------------

def _crash_universe():
    """One stock: enough Jan history to be scored, bought at 100, climbs to 120,
    then crashes to 80 over the first days of Feb."""
    jan = [date(2025, 1, d) for d in range(20, 32)]       # 20..31, rebalance on 31
    feb = [date(2025, 2, d) for d in range(1, 6)]         # 1..5, rebalance on 5
    ds = tuple(jan + feb)
    a = (90, 92, 94, 96, 98, 100, 102, 104, 106, 108, 110, 100,   # Jan history, buy @100
         110, 120, 100, 90, 80)                                    # Feb: peak 120 -> crash
    return {"A": Series("A", ds, a)}


def test_per_stock_trailing_stop_exits_a_crashing_winner():
    cfg = StrategyConfig(name="ts", top_n=1, lookback_short=2, lookback_long=3,
                         regime_mode="none", trail_stop_mode="per_stock",
                         trail_stop_pct=0.15)
    stop = run_strategy(_crash_universe(), index=None, cfg=cfg, costs=FREE)
    none = run_strategy(_crash_universe(), index=None,
                        cfg=replace(cfg, trail_stop_mode="none"), costs=FREE)
    sc = dict(stop.equity_curve)
    # It must HOLD through the run-up (not stop early), then exit on the breach:
    assert sc[date(2025, 2, 1)] == pytest.approx(550_000.0)   # still holding at 110
    assert sc[date(2025, 2, 2)] == pytest.approx(600_000.0)   # still holding at the 120 peak
    # Peak 120 on Feb 2; Feb 3 close 100 breaches 120*0.85=102 -> exit to cash.
    assert sc[date(2025, 2, 4)] == pytest.approx(500_000.0)   # in cash, dodged the 90
    assert dict(none.equity_curve)[date(2025, 2, 4)] == pytest.approx(450_000.0)  # rode it
    assert stop.end_equity == pytest.approx(500_000.0)
    assert none.end_equity == pytest.approx(400_000.0)
    assert stop.end_equity > none.end_equity


def test_portfolio_trailing_stop_liquidates_on_equity_drawdown():
    cfg = StrategyConfig(name="pt", top_n=1, lookback_short=2, lookback_long=3,
                         regime_mode="none", trail_stop_mode="portfolio",
                         trail_stop_pct=0.15)
    res = run_strategy(_crash_universe(), index=None, cfg=cfg, costs=FREE)
    # Equity peak 6L (Feb 2); Feb 3 at 5L breaches 6L*0.85=5.1L -> liquidate all.
    assert dict(res.equity_curve)[date(2025, 2, 4)] == pytest.approx(500_000.0)
    assert res.end_equity == pytest.approx(500_000.0)


def test_trailing_stop_none_is_inert():
    """The stop code must be byte-identical to base when disarmed."""
    cfg = StrategyConfig(name="n", top_n=1, lookback_short=2, lookback_long=3,
                         regime_mode="none")
    a = run_strategy(_crash_universe(), index=None, cfg=cfg, costs=EquityCostConfig())
    b = run_strategy(_crash_universe(), index=None,
                     cfg=replace(cfg, trail_stop_mode="none", trail_stop_pct=0.0),
                     costs=EquityCostConfig())
    _curves_equal(a.equity_curve, b.equity_curve)


# -- every mode at least runs and stays solvent (integration smoke) --------

@pytest.mark.parametrize("cfg", [
    StrategyConfig(name="skip", rank_mode="skip_month", regime_mode="none",
                   lookback_short=2, lookback_long=3, skip=1, top_n=2),
    StrategyConfig(name="tq", rank_mode="trend_quality", regime_mode="none",
                   lookback_short=2, lookback_long=3, tq_span=3, top_n=2),
    StrategyConfig(name="dd", rank_mode="downside", regime_mode="none",
                   lookback_short=2, lookback_long=3, top_n=2),
    StrategyConfig(name="iv", weight_mode="inverse_vol", regime_mode="none",
                   lookback_short=2, lookback_long=3, weight_vol_span=2, top_n=2),
    StrategyConfig(name="sp", weight_mode="score_prop", regime_mode="none",
                   lookback_short=2, lookback_long=3, top_n=2),
])
def test_modes_run_and_stay_solvent(cfg):
    uni = three_stock_universe()
    res = run_strategy(uni, index=None, cfg=cfg, costs=EquityCostConfig())
    assert res.rebalances == 2
    assert res.end_equity > 0
    assert len(res.equity_curve) == 8
