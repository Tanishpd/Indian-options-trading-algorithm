"""Generalised momentum engine for the disciplined indicator search (docs/15).

The base momentum backtest (`momentum.backtest`) is deliberately left untouched
and pinned. This module RE-implements the same loop but with four pluggable
axes, so a pre-registered set of ~20 configs can be scored on identical data:

  - rank_mode     : how stocks are scored/ranked (base / skip_month / residual /
                    trend_quality / downside)
  - weight_mode   : how the top-N is sized (equal / inverse_vol / score_prop)
  - regime_mode   : the market on/off (or soft) gate (price_sma / slope_sma /
                    breadth / macd / dispersion / none)
  - exposure_mode : total-exposure scaling (binary / vol_target)

Two invariants make this trustworthy rather than a second, subtly-different
engine:

  1. With the default StrategyConfig (rank=base, weight=equal, regime=price_sma,
     exposure=binary, tax off) it reproduces `momentum.backtest` EXACTLY — pinned
     by test, and on real data it must return the base 23.6% / 21.3% / 1.51.
  2. Costs AND the 20% STCG tax are inside the returned equity curve, so every
     config is judged net — a high-turnover overlay carries its own drag. The
     honest bar to beat is base NET, not base gross.

Nothing here fetches data or decides anything; it runs configs that are
constructed as data (see run_indicator_search.py). No config is discovered
mid-run — that is the whole point (docs/11's "keep the best backtest" trap).
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date

from ..data.equity import Series, month_end_days, trading_days
from .momentum import EquityCostConfig, _z, members_asof, trade_cost
from . import indicators as ind


@dataclass(frozen=True)
class StrategyConfig:
    """One fully-specified strategy. Defaults ARE the base momentum config, so a
    config is just the base with a few fields overridden. `mechanism` is the
    ex-ante economic thesis — required by the pre-registration discipline."""

    name: str
    mechanism: str = ""

    # -- ranking --
    top_n: int = 30
    lookback_short: int = 126
    lookback_long: int = 252
    rank_mode: str = "base"            # base|skip_month|residual|trend_quality|downside
    skip: int = 21                     # skip_month: drop the most recent ~month
    resid_lookback: int = 252          # residual: OLS window for beta
    tq_span: int = 126                 # trend_quality: R^2 window
    tq_weight: float = 0.5             # trend_quality: blend weight on the tilt

    # -- weighting within the top-N --
    weight_mode: str = "equal"         # equal|inverse_vol|score_prop
    weight_vol_span: int = 63

    # -- regime gate --
    regime_mode: str = "price_sma"     # price_sma|slope_sma|breadth|macd|dispersion|none
    regime_sma: int = 200
    slope_k: int = 21
    breadth_ma: int = 50
    breadth_thresh: float = 0.5
    breadth_combine: bool = False      # AND the breadth gate with price>200-DMA
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    disp_warmup: int = 12              # dispersion: rebalances before the gate arms
    disp_span: int = 63

    # -- exposure scaling --
    exposure_mode: str = "binary"      # binary|vol_target
    target_vol: float = 0.15           # annualised, vol_target
    vol_lookback: int = 63
    exposure_floor: float = 0.0
    exposure_cap: float = 1.0

    # -- tax --
    apply_stcg: bool = False
    stcg_rate: float = 0.20            # short-term capital gains, realised annually


# --------------------------------------------------------------------------
# scoring (the rank_mode axis)
# --------------------------------------------------------------------------

def _index_returns_by_date(index: Series | None) -> dict[date, float]:
    """Map trading date -> index daily simple return, for residual regressions."""
    if index is None:
        return {}
    out: dict[date, float] = {}
    for k in range(1, len(index.closes)):
        prev = index.closes[k - 1]
        if prev > 0:
            out[index.dates[k]] = index.closes[k] / prev - 1.0
    return out


def _base_pair(s: Series, i: int, cfg: StrategyConfig) -> tuple[float, float] | None:
    """(short, long) volatility-adjusted returns for the base/skip_month/downside
    ranks. Uses the SAME Series helpers as momentum.backtest so base reproduces."""
    r_s = s.lookback_return(i, cfg.lookback_short)
    if cfg.rank_mode == "skip_month":
        r_l = ind.skip_month_return(s.closes, i, cfg.lookback_long, cfg.skip)
    else:
        r_l = s.lookback_return(i, cfg.lookback_long)
    if cfg.rank_mode == "downside":
        v_s = ind.downside_deviation(s.closes, i, cfg.lookback_short, annualize=False)
        v_l = ind.downside_deviation(s.closes, i, cfg.lookback_long, annualize=False)
    else:
        v_s = s.daily_vol(i, cfg.lookback_short)
        v_l = s.daily_vol(i, cfg.lookback_long)
    if None in (r_s, v_s, r_l, v_l) or v_s <= 0 or v_l <= 0:
        return None
    return r_s / v_s, r_l / v_l


def _residual_pair(s: Series, i: int, cfg: StrategyConfig,
                   idx_ret: dict[date, float]) -> tuple[float, float] | None:
    """Residual-momentum score over the short and long windows: regress the
    stock's daily returns on the index's, take the Sharpe of the residuals
    (mean/stdev). Strips the market-beta component that drives momentum crashes
    (Blitz-Huij-Martens)."""
    out = []
    for span in (cfg.lookback_short, cfg.lookback_long):
        if i - span < 1:
            return None
        ys, xs = [], []
        for k in range(i - span + 1, i + 1):
            prev = s.closes[k - 1]
            if prev <= 0:
                continue
            ir = idx_ret.get(s.dates[k])
            if ir is None:
                continue
            ys.append(s.closes[k] / prev - 1.0)
            xs.append(ir)
        if len(ys) < 20:
            return None
        ba = ind.ols_beta_alpha(ys, xs)
        if ba is None:
            return None
        beta, _alpha = ba
        # Keep the idiosyncratic drift (alpha) IN the residual — subtract only the
        # market component beta*x. Subtracting the fitted alpha too would force the
        # residual mean to zero (OLS guarantees sum of residuals = 0), collapsing
        # the score to noise. residual = alpha + e_t, so mean(residual) = alpha is
        # exactly the stock-specific trend residual momentum is meant to rank on
        # (Blitz-Huij-Martens).
        resid = [y - beta * x for y, x in zip(ys, xs)]
        if len(resid) < 2:
            return None
        sd = statistics.stdev(resid)
        if sd <= 0:
            return None
        out.append(statistics.mean(resid) / sd)
    return out[0], out[1]


def score_universe(series: dict[str, Series], index: Series | None, day: date,
                   cfg: StrategyConfig, members: frozenset[str] | None,
                   idx_ret: dict[date, float]) -> dict[str, float]:
    """Composite score per eligible symbol as of `day`, per the rank_mode. Uses
    only bars on or before `day`."""
    raw_s: dict[str, float] = {}
    raw_l: dict[str, float] = {}
    for sym, s in series.items():
        if members is not None and sym not in members:
            continue
        i = s.index_on_or_before(day)
        if i is None:
            continue
        pair = (_residual_pair(s, i, cfg, idx_ret) if cfg.rank_mode == "residual"
                else _base_pair(s, i, cfg))
        if pair is None:
            continue
        raw_s[sym], raw_l[sym] = pair
    zs, zl = _z(raw_s), _z(raw_l)
    comp = {sym: (zs[sym] + zl[sym]) / 2.0 for sym in raw_s}

    if cfg.rank_mode == "trend_quality":
        tq: dict[str, float] = {}
        for sym in comp:
            s = series[sym]
            i = s.index_on_or_before(day)
            q = ind.trend_quality_r2(s.closes, i, cfg.tq_span)
            if q is not None:
                tq[sym] = q
        ztq = _z(tq)
        comp = {sym: (1.0 - cfg.tq_weight) * comp[sym] + cfg.tq_weight * ztq.get(sym, 0.0)
                for sym in comp}
    return comp


# --------------------------------------------------------------------------
# regime + exposure (the regime_mode / exposure_mode axes)
# --------------------------------------------------------------------------

def _breadth(series: dict[str, Series], day: date, cfg: StrategyConfig,
             members: frozenset[str] | None) -> float | None:
    num = den = 0
    for sym, s in series.items():
        if members is not None and sym not in members:
            continue
        j = s.index_on_or_before(day)
        if j is None:
            continue
        sma = ind.sma(s.closes, j, cfg.breadth_ma)
        if sma is None:
            continue
        den += 1
        num += 1 if s.closes[j] >= sma else 0
    return None if den == 0 else num / den


def _cross_dispersion(series: dict[str, Series], day: date, cfg: StrategyConfig,
                      members: frozenset[str] | None) -> float | None:
    """Cross-sectional stdev of member trailing returns — momentum pays when
    stocks move apart, not together."""
    rets = []
    for sym, s in series.items():
        if members is not None and sym not in members:
            continue
        j = s.index_on_or_before(day)
        if j is None:
            continue
        r = s.lookback_return(j, cfg.disp_span)
        if r is not None:
            rets.append(r)
    return statistics.pstdev(rets) if len(rets) >= 2 else None


def _regime_gate(index: Series | None, series: dict[str, Series], day: date,
                 cfg: StrategyConfig, members: frozenset[str] | None,
                 disp_hist: list[float]) -> float:
    """Return an exposure fraction in [0, 1] from the regime signal. 1.0 = fully
    invested (or filter disabled / not enough history — never gate on ignorance)."""
    if cfg.regime_mode == "none":
        return 1.0
    if cfg.regime_mode == "breadth":
        br = _breadth(series, day, cfg, members)
        if br is None:
            return 1.0
        gate = 1.0 if br >= cfg.breadth_thresh else 0.0
        if cfg.breadth_combine and index is not None:
            i = index.index_on_or_before(day)
            sma = ind.sma(index.closes, i, cfg.regime_sma) if i is not None else None
            if sma is not None and index.closes[i] < sma:
                gate = 0.0
        return gate
    if cfg.regime_mode == "dispersion":
        d = _cross_dispersion(series, day, cfg, members)
        if d is None:
            return 1.0
        if len(disp_hist) < cfg.disp_warmup:
            disp_hist.append(d)
            return 1.0
        med = statistics.median(disp_hist)
        disp_hist.append(d)
        return 1.0 if d >= med else cfg.exposure_floor

    if index is None:
        return 1.0
    i = index.index_on_or_before(day)
    if i is None:
        return 1.0
    if cfg.regime_mode == "price_sma":
        sma = ind.sma(index.closes, i, cfg.regime_sma)
        return 1.0 if sma is None or index.closes[i] >= sma else 0.0
    if cfg.regime_mode == "slope_sma":
        sl = ind.sma_slope(index.closes, i, cfg.regime_sma, cfg.slope_k)
        return 1.0 if sl is None or sl > 0 else 0.0
    if cfg.regime_mode == "macd":
        m = ind.macd(index.closes, i, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
        return 1.0 if m is None or m[0] >= m[1] else 0.0
    return 1.0


def _voltarget_scale(index: Series | None, day: date, cfg: StrategyConfig) -> float:
    if cfg.exposure_mode != "vol_target" or index is None:
        return 1.0
    i = index.index_on_or_before(day)
    if i is None:
        return 1.0
    rv = ind.realized_vol(index.closes, i, cfg.vol_lookback, annualize=True)
    if rv is None or rv <= 0:
        return 1.0
    return max(cfg.exposure_floor, min(cfg.exposure_cap, cfg.target_vol / rv))


# --------------------------------------------------------------------------
# result
# --------------------------------------------------------------------------

@dataclass
class StrategyResult:
    equity_curve: list[tuple[date, float]]
    start_capital: float
    rebalances: int = 0
    in_cash_rebalances: int = 0
    costs_paid: float = 0.0
    tax_paid: float = 0.0
    turnover_fracs: list[float] = field(default_factory=list)

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
        if not self.equity_curve:
            return 0.0
        peak = self.equity_curve[0][1]
        worst = 0.0
        for _, v in self.equity_curve:
            peak = max(peak, v)
            if peak > 0:
                worst = max(worst, (peak - v) / peak)
        return 100.0 * worst

    @property
    def sharpe(self) -> float:
        rets = [self.equity_curve[i][1] / self.equity_curve[i - 1][1] - 1.0
                for i in range(1, len(self.equity_curve))
                if self.equity_curve[i - 1][1] > 0]
        if len(rets) < 2:
            return float("nan")
        sd = statistics.stdev(rets)
        return (statistics.mean(rets) / sd * math.sqrt(252)) if sd else float("nan")

    def monthly_returns(self) -> list[tuple[date, float]]:
        """Month-end (date, simple return) pairs — the clock the overfitting
        statistics run on. First month has no prior mark, so it is dropped."""
        val = dict(self.equity_curve)
        ends = month_end_days([d for d, _ in self.equity_curve])
        out: list[tuple[date, float]] = []
        for a, b in zip(ends, ends[1:]):
            pa, pb = val[a], val[b]
            if pa > 0:
                out.append((b, pb / pa - 1.0))
        return out


def _fy(day: date) -> int:
    """Indian fiscal year key: Apr-Mar. 2025-05 -> 2025; 2025-02 -> 2024."""
    return day.year if day.month >= 4 else day.year - 1


# --------------------------------------------------------------------------
# the backtest
# --------------------------------------------------------------------------

def run_strategy(series: dict[str, Series], index: Series | None,
                 cfg: StrategyConfig, costs: EquityCostConfig,
                 start_capital: float = 500_000.0,
                 membership: list[tuple[date, frozenset[str]]] | None = None
                 ) -> StrategyResult:
    """Monthly-rebalanced strategy, marked daily, costs AND STCG inside the curve.

    Reproduces momentum.backtest exactly under the default config; the pluggable
    axes only take effect when a field is overridden."""
    days = trading_days(series)
    if not days:
        return StrategyResult([], start_capital)
    rebal = set(month_end_days(days))
    idx_ret = _index_returns_by_date(index) if cfg.rank_mode == "residual" else {}

    cash = start_capital
    shares: dict[str, float] = {}
    basis: dict[str, float] = {}          # average cost per share, for realised gains
    disp_hist: list[float] = []
    res = StrategyResult([], start_capital)

    fy_realized = 0.0                      # realised short-term gains this fiscal year
    loss_carry = 0.0                       # carried-forward short-term losses
    prev_fy: int | None = None

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

    def settle_fy() -> None:
        nonlocal cash, fy_realized, loss_carry
        net = fy_realized
        if net > 0:
            taxable = max(0.0, net - loss_carry)
            loss_carry = max(0.0, loss_carry - net)
            tax = cfg.stcg_rate * taxable
            cash -= tax
            res.tax_paid += tax
        else:
            loss_carry += -net
        fy_realized = 0.0

    for day in days:
        if cfg.apply_stcg:
            cur_fy = _fy(day)
            if prev_fy is not None and cur_fy != prev_fy:
                settle_fy()
            prev_fy = cur_fy

        if day in rebal:
            equity = portfolio_value(day)
            gate = _regime_gate(index, series, day, cfg, members_asof(membership, day),
                                disp_hist)
            exposure = gate * _voltarget_scale(index, day, cfg)

            if exposure <= 0.0:
                target: dict[str, float] = {}
                res.in_cash_rebalances += 1
            else:
                members = members_asof(membership, day)
                scores = score_universe(series, index, day, cfg, members, idx_ret)
                winners = sorted(scores, key=scores.get, reverse=True)[: cfg.top_n]
                winners = [w for w in winners if close_on(w, day)]
                target = _weights(series, day, cfg, winners, scores, exposure * equity)

            traded = 0.0
            for sym in set(shares) | set(target):
                px = close_on(sym, day)
                if px is None or px <= 0:
                    continue
                cur_shares = shares.get(sym, 0.0)
                delta = target.get(sym, 0.0) - cur_shares * px
                if abs(delta) < 1e-6:
                    continue
                traded += abs(delta)
                c = trade_cost(abs(delta), is_buy=delta > 0, cfg=costs)
                cash -= c
                res.costs_paid += c
                if delta > 0:                                   # buy: update avg basis
                    add = delta / px
                    new = cur_shares + add
                    basis[sym] = (cur_shares * basis.get(sym, px) + add * px) / new
                    shares[sym] = new
                else:                                           # sell: realise a gain
                    sold = -delta / px
                    fy_realized += sold * (px - basis.get(sym, px))
                    shares[sym] = cur_shares - sold
                cash -= delta
            shares = {k: v for k, v in shares.items() if v > 1e-9}
            basis = {k: v for k, v in basis.items() if k in shares}
            res.rebalances += 1
            res.turnover_fracs.append(traded / equity if equity > 0 else 0.0)

        res.equity_curve.append((day, portfolio_value(day)))

    if cfg.apply_stcg:
        settle_fy()                          # tax the final (partial) fiscal year
        if res.equity_curve:
            d, _ = res.equity_curve[-1]
            res.equity_curve[-1] = (d, portfolio_value(d))
    return res


def _weights(series: dict[str, Series], day: date, cfg: StrategyConfig,
             winners: list[str], scores: dict[str, float], invested: float
             ) -> dict[str, float]:
    """Rupee target per winner given the weight_mode and total `invested` capital."""
    if not winners:
        return {}
    if cfg.weight_mode == "inverse_vol":
        iv: dict[str, float] = {}
        for w in winners:
            s = series[w]
            i = s.index_on_or_before(day)
            v = ind.realized_vol(s.closes, i, cfg.weight_vol_span, annualize=False)
            iv[w] = 1.0 / v if v and v > 0 else 0.0
        tot = sum(iv.values())
        wt = {w: (iv[w] / tot if tot > 0 else 1.0 / len(winners)) for w in winners}
    elif cfg.weight_mode == "score_prop":
        mn = min(scores[w] for w in winners)
        sh = {w: scores[w] - mn + 1e-9 for w in winners}
        tot = sum(sh.values())
        wt = {w: sh[w] / tot for w in winners}
    else:                                     # equal
        wt = {w: 1.0 / len(winners) for w in winners}
    return {w: invested * wt[w] for w in winners}
