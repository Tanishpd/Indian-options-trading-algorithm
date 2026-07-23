"""NIFTY 200 Momentum 30 — the one externally-corroborated edge (docs/14).

Two independent research passes on this project reached the same conclusion:
the durable, primary-source-backed edge in Indian equities is momentum, not
option premium. This module implements the NSE Indices methodology as a
backtestable, cost-honest strategy so the claim can be tested on our own data
rather than taken from an AMC leaflet.

The rules (NSE Nifty200 Momentum 30 methodology, adapted):

  - Universe: a supplied set of liquid stocks (Nifty 200 in practice).
  - Score each stock by TWO volatility-adjusted returns — 6-month and 12-month
    price return, each divided by the daily-return volatility over the same
    window. Dividing by volatility is what stops the score chasing junk that
    merely moved a lot.
  - z-score each of the two across the universe, average them: the composite.
  - Hold the top N, equal-weighted. Rebalance monthly.
  - Optional regime filter: hold cash whenever the index closes below its
    200-day average. The framework and Raju (2019) both show this roughly
    halves the drawdown, which is the whole point for a capital-preservation
    mandate.

What this does NOT do, and says so rather than hiding it: it does not model
STCG tax (realised, annual — reported separately), and it runs on whatever
universe you supply. A CURRENT Nifty 200 list applied to history is survivorship
bias; a point-in-time membership list is the honest input. The backtest is
correct; its verdict is only as good as the universe fed to it.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date

from ..data.equity import Series, month_end_days, trading_days

# 21 trading days/month is the NSE convention used throughout.
DAYS_6M = 126
DAYS_12M = 252


@dataclass(frozen=True)
class EquityCostConfig:
    """Delivery-equity costs. Defaults land at ~30 bps round trip incl. slippage,
    matching the framework's honest cost table (docs/14)."""

    brokerage_per_order: float = 0.0        # Zerodha CNC delivery is free
    stt_rate: float = 0.001                 # 0.1% delivery, BOTH sides
    txn_rate: float = 0.0000297             # NSE cash txn charge
    sebi_rate: float = 0.000001
    stamp_rate: float = 0.00015             # 0.015%, BUY side only
    gst_rate: float = 0.18                  # on brokerage + txn + sebi
    slippage_rate: float = 0.0005           # 5 bps/side; equities have real spread


def trade_cost(value: float, is_buy: bool, cfg: EquityCostConfig) -> float:
    """Cost of one order for `value` rupees. STT both sides; stamp buy-only; GST
    rides only on brokerage+txn+sebi, never on STT or stamp (docs/05 rule)."""
    brokerage = cfg.brokerage_per_order
    txn = cfg.txn_rate * value
    sebi = cfg.sebi_rate * value
    gst = cfg.gst_rate * (brokerage + txn + sebi)
    stt = cfg.stt_rate * value
    stamp = cfg.stamp_rate * value if is_buy else 0.0
    slip = cfg.slippage_rate * value
    return brokerage + txn + sebi + gst + stt + stamp + slip


@dataclass(frozen=True)
class MomentumParams:
    top_n: int = 30
    lookback_short: int = DAYS_6M
    lookback_long: int = DAYS_12M
    use_regime_filter: bool = True
    regime_sma: int = 200


def _score_one(s: Series, i: int, p: MomentumParams) -> tuple[float, float] | None:
    """(short, long) raw volatility-adjusted returns, or None if too short."""
    r_s = s.lookback_return(i, p.lookback_short)
    v_s = s.daily_vol(i, p.lookback_short)
    r_l = s.lookback_return(i, p.lookback_long)
    v_l = s.daily_vol(i, p.lookback_long)
    if None in (r_s, v_s, r_l, v_l) or v_s <= 0 or v_l <= 0:
        return None
    return r_s / v_s, r_l / v_l


def _z(values: dict[str, float]) -> dict[str, float]:
    if len(values) < 2:
        return {k: 0.0 for k in values}
    mu = statistics.mean(values.values())
    sd = statistics.pstdev(values.values())
    if sd == 0:
        return {k: 0.0 for k in values}
    return {k: (v - mu) / sd for k, v in values.items()}


def members_asof(schedule: list[tuple[date, frozenset[str]]] | None,
                 day: date) -> frozenset[str] | None:
    """The index membership in force on `day`: the most recent snapshot at or
    before it. None means "no restriction" (use the whole supplied universe).

    This is the fix for survivorship bias. Without it, a backtest scores every
    symbol that exists TODAY across all history, silently excluding the stocks
    that fell out of the index — the failures — and overstating the result. With
    a point-in-time schedule, each rebalance sees only the index as it actually
    stood then (docs/14)."""
    if not schedule:
        return None
    out: frozenset[str] | None = None
    for eff, members in schedule:               # schedule is ascending by date
        if eff <= day:
            out = members
        else:
            break
    return out


def momentum_scores(series: dict[str, Series], day: date,
                    p: MomentumParams,
                    members: frozenset[str] | None = None) -> dict[str, float]:
    """Composite momentum score per eligible symbol, as of `day` (uses only bars
    on or before `day` — no look-ahead). If `members` is given, only symbols in
    that point-in-time index membership are scored."""
    raw_s: dict[str, float] = {}
    raw_l: dict[str, float] = {}
    for sym, s in series.items():
        if members is not None and sym not in members:
            continue
        i = s.index_on_or_before(day)
        if i is None:
            continue
        sc = _score_one(s, i, p)
        if sc is None:
            continue
        raw_s[sym], raw_l[sym] = sc
    zs, zl = _z(raw_s), _z(raw_l)
    return {sym: (zs[sym] + zl[sym]) / 2.0 for sym in raw_s}


def _regime_ok(index: Series, day: date, p: MomentumParams) -> bool:
    """True if the index is at or above its N-day average (or filter disabled)."""
    if not p.use_regime_filter or index is None:
        return True
    i = index.index_on_or_before(day)
    if i is None or i + 1 < p.regime_sma:
        return True                            # not enough history: don't gate
    sma = statistics.mean(index.closes[i - p.regime_sma + 1: i + 1])
    return index.closes[i] >= sma


@dataclass
class MomentumResult:
    equity_curve: list[tuple[date, float]]
    start_capital: float
    rebalances: int
    turnover_fracs: list[float] = field(default_factory=list)
    costs_paid: float = 0.0
    in_cash_rebalances: int = 0

    @property
    def end_equity(self) -> float:
        return self.equity_curve[-1][1] if self.equity_curve else self.start_capital

    @property
    def years(self) -> float:
        if len(self.equity_curve) < 2:
            return 0.0
        return (self.equity_curve[-1][0] - self.equity_curve[0][0]).days / 365.25

    @property
    def cagr_pct(self) -> float:
        if self.years <= 0 or self.start_capital <= 0 or self.end_equity <= 0:
            return float("nan")
        return 100.0 * ((self.end_equity / self.start_capital) ** (1 / self.years) - 1)

    @property
    def max_drawdown_pct(self) -> float:
        peak = worst = 0.0
        peak = self.equity_curve[0][1] if self.equity_curve else 0.0
        for _, v in self.equity_curve:
            peak = max(peak, v)
            if peak > 0:
                worst = max(worst, (peak - v) / peak)
        return 100.0 * worst

    @property
    def sharpe(self) -> float:
        rets = [
            self.equity_curve[i][1] / self.equity_curve[i - 1][1] - 1.0
            for i in range(1, len(self.equity_curve))
            if self.equity_curve[i - 1][1] > 0
        ]
        if len(rets) < 2:
            return float("nan")
        sd = statistics.stdev(rets)
        return (statistics.mean(rets) / sd * math.sqrt(252)) if sd else float("nan")

    @property
    def avg_turnover_pct(self) -> float:
        return 100.0 * statistics.mean(self.turnover_fracs) if self.turnover_fracs else 0.0


def backtest(series: dict[str, Series], index: Series | None,
             params: MomentumParams, costs: EquityCostConfig,
             start_capital: float = 500_000.0,
             membership: list[tuple[date, frozenset[str]]] | None = None
             ) -> MomentumResult:
    """Monthly-rebalanced top-N momentum, marked daily, costs on every trade.

    `membership`, if given, is a point-in-time index schedule (ascending
    (effective_date, member-set) snapshots). Each rebalance then picks from the
    index as it stood on that date, removing survivorship bias. Without it, the
    whole supplied `series` is the eligible universe on every date — an
    optimistic ceiling (docs/14)."""
    days = trading_days(series)
    if not days:
        return MomentumResult([], start_capital, 0)
    rebal = set(month_end_days(days))

    cash = start_capital
    shares: dict[str, float] = {}
    res = MomentumResult([], start_capital, 0)

    def close_on(sym: str, day: date) -> float | None:
        s = series[sym]
        i = s.index_on_or_before(day)
        return None if i is None else s.closes[i]

    def portfolio_value(day: date) -> float:
        total = cash
        for sym, q in shares.items():
            px = close_on(sym, day)
            if px is not None:
                total += q * px
        return total

    for day in days:
        if day in rebal:
            equity = portfolio_value(day)
            if not _regime_ok(index, day, params):
                target: dict[str, float] = {}          # regime off: go to cash
                res.in_cash_rebalances += 1
            else:
                members = members_asof(membership, day)
                scores = momentum_scores(series, day, params, members)
                winners = sorted(scores, key=scores.get, reverse=True)[: params.top_n]
                winners = [w for w in winners if close_on(w, day)]
                per = equity / len(winners) if winners else 0.0
                target = {w: per for w in winners}

            # Reconcile current -> target, charging each leg honestly.
            traded = 0.0
            held_syms = set(shares) | set(target)
            for sym in held_syms:
                px = close_on(sym, day)
                if px is None or px <= 0:
                    continue
                cur_val = shares.get(sym, 0.0) * px
                tgt_val = target.get(sym, 0.0)
                delta = tgt_val - cur_val
                if abs(delta) < 1e-6:
                    continue
                traded += abs(delta)
                c = trade_cost(abs(delta), is_buy=delta > 0, cfg=costs)
                cash -= c
                res.costs_paid += c
                cash -= delta                          # buy spends cash, sell adds
                shares[sym] = tgt_val / px
            shares = {k: v for k, v in shares.items() if v > 1e-9}
            res.rebalances += 1
            res.turnover_fracs.append(traded / equity if equity > 0 else 0.0)

        res.equity_curve.append((day, portfolio_value(day)))

    return res
