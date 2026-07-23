"""Closes-only technical-indicator helpers for the momentum backtester.

Every function here is a pure map from a price series (a sequence of daily
closes) and an integer index `i` into it, to a single number (or a small tuple).
The contract shared by all of them, and the reason this module exists as its own
layer, is the no-look-ahead rule: an indicator evaluated at bar `i` may read only
bars at or before `i`. A backtester that respects this can trust that a signal it
acts on at `i` could genuinely have been computed on the morning of day `i`.

Conventions match `optionsbot.data.equity.Series`:
  * insufficient history returns None (never raises) — the caller decides what a
    missing signal means, exactly as `Series.lookback_return` / `Series.rsi` do;
  * volatility uses sample stdev (ddof=1), matching `Series.daily_vol`;
  * nothing here mutates its inputs or depends on anything but the closes passed.

No third-party dependencies: `math` and `statistics` from the stdlib only.
"""
from __future__ import annotations

import math
import statistics
from collections.abc import Sequence


def sma(closes: Sequence[float], i: int, n: int) -> float | None:
    """Simple mean of closes[i-n+1 .. i]. None if the window runs off the start."""
    if n <= 0 or i - n + 1 < 0:
        return None
    window = closes[i - n + 1 : i + 1]
    return sum(window) / n


def ema(closes: Sequence[float], i: int, n: int) -> float | None:
    """Exponential moving average with alpha = 2/(n+1), as of index i.

    The EMA is seeded at the first full window (index n-1) with the SMA of the
    first n bars, then iterated forward one bar at a time to i. None if there are
    fewer than n bars up to and including i (i.e. i < n-1)."""
    if n <= 0 or i - n + 1 < 0:
        return None
    alpha = 2.0 / (n + 1.0)
    value = sum(closes[0:n]) / n            # seed: SMA of the first n bars, at index n-1
    for k in range(n, i + 1):               # iterate forward to i
        value = alpha * closes[k] + (1.0 - alpha) * value
    return value


def wma(closes: Sequence[float], i: int, n: int) -> float | None:
    """Linearly weighted moving average: weights 1..n, newest (closes[i]) heaviest.

    None if the window runs off the start."""
    if n <= 0 or i - n + 1 < 0:
        return None
    num = 0.0
    for w in range(1, n + 1):               # w=1 is oldest bar, w=n is closes[i]
        num += w * closes[i - n + w]
    denom = n * (n + 1) / 2.0               # sum of weights 1..n
    return num / denom


def sma_slope(closes: Sequence[float], i: int, n: int, k: int = 1) -> float | None:
    """Fractional change in the n-bar SMA over the last k bars: sma(i)/sma(i-k) - 1.

    None if either SMA is undefined (or the earlier one is non-positive)."""
    now = sma(closes, i, n)
    prev = sma(closes, i - k, n)
    if now is None or prev is None or prev == 0:
        return None
    return now / prev - 1.0


def dist_from_sma(closes: Sequence[float], i: int, n: int) -> float | None:
    """How far above/below its n-bar SMA the close sits: closes[i]/sma(i,n) - 1."""
    base = sma(closes, i, n)
    if base is None or base == 0:
        return None
    return closes[i] / base - 1.0


def roc(closes: Sequence[float], i: int, n: int) -> float | None:
    """n-bar rate of change: closes[i]/closes[i-n] - 1.

    None if i-n < 0 or the reference close is non-positive."""
    if i - n < 0 or closes[i - n] <= 0:
        return None
    return closes[i] / closes[i - n] - 1.0


def skip_month_return(
    closes: Sequence[float], i: int, long: int = 252, skip: int = 21
) -> float | None:
    """The 12-1 momentum return: from ~`long` bars ago to ~`skip` bars ago.

    closes[i-skip]/closes[i-long] - 1. Skipping the most recent `skip` bars is the
    standard defence against short-term mean reversion. None if i-long < 0 (or the
    reference close is non-positive)."""
    if i - long < 0 or closes[i - long] <= 0:
        return None
    return closes[i - skip] / closes[i - long] - 1.0


def _returns_ending_at(closes: Sequence[float], i: int, span: int) -> list[float]:
    """The last `span` daily simple returns ending at index i (fewer near the start).

    A return at bar k reads closes[k] and closes[k-1], so the earliest possible is
    at k=1. Mirrors the window `Series.daily_vol` uses when i-span >= 0."""
    start = max(1, i - span + 1)
    return [
        closes[k] / closes[k - 1] - 1.0
        for k in range(start, i + 1)
        if closes[k - 1] > 0
    ]


def realized_vol(
    closes: Sequence[float],
    i: int,
    span: int,
    annualize: bool = True,
    periods: int = 252,
) -> float | None:
    """Sample stdev (ddof=1) of the last `span` daily returns ending at i.

    Multiplied by sqrt(periods) when `annualize`. None if fewer than 2 returns are
    available. On a window with i-span >= 0 this equals `Series.daily_vol` (times
    the annualisation factor)."""
    rets = _returns_ending_at(closes, i, span)
    if len(rets) < 2:
        return None
    vol = statistics.stdev(rets)
    return vol * math.sqrt(periods) if annualize else vol


def downside_deviation(
    closes: Sequence[float],
    i: int,
    span: int,
    periods: int = 252,
    annualize: bool = True,
) -> float | None:
    """Downside deviation: sqrt(mean(min(r,0)^2)) over the last `span` daily returns.

    Only negative returns contribute; the mean divides by the return count (not
    count-1), matching the usual downside-deviation definition. Multiplied by
    sqrt(periods) when `annualize`. None if fewer than 1 return is available."""
    rets = _returns_ending_at(closes, i, span)
    if len(rets) < 1:
        return None
    downside = sum(min(r, 0.0) ** 2 for r in rets) / len(rets)
    dd = math.sqrt(downside)
    return dd * math.sqrt(periods) if annualize else dd


def _ema_at_each(closes: Sequence[float], n: int) -> list[float | None]:
    """EMA(n) evaluated at every index: value at j, or None while j < n-1."""
    out: list[float | None] = [None] * len(closes)
    if n <= 0 or len(closes) < n:
        return out
    alpha = 2.0 / (n + 1.0)
    value = sum(closes[0:n]) / n
    out[n - 1] = value
    for k in range(n, len(closes)):
        value = alpha * closes[k] + (1.0 - alpha) * value
        out[k] = value
    return out


def macd(
    closes: Sequence[float],
    i: int,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[float, float, float] | None:
    """MACD as of index i: (macd_line, signal_line, histogram).

    macd_line = ema(fast) - ema(slow), defined once both EMAs exist (index slow-1).
    signal_line = EMA of the macd_line *series* with span `signal`, seeded as the
    SMA of the first `signal` macd values. histogram = macd_line - signal_line.
    None until there is enough history to seed the signal line, i.e. while
    i < slow + signal - 2."""
    if slow <= 0 or fast <= 0 or signal <= 0:
        return None
    j0 = slow - 1                           # first index where macd_line is defined
    if i < j0 + signal - 1:                 # not enough macd values to seed the signal
        return None
    fast_ema = _ema_at_each(closes, fast)
    slow_ema = _ema_at_each(closes, slow)
    macd_series = [
        f - s for f, s in zip(fast_ema[j0 : i + 1], slow_ema[j0 : i + 1])
    ]                                       # aligned to indices j0 .. i
    alpha = 2.0 / (signal + 1.0)
    sig = sum(macd_series[0:signal]) / signal   # seed at index j0+signal-1
    for m in macd_series[signal:]:
        sig = alpha * m + (1.0 - alpha) * sig
    macd_line = macd_series[-1]
    return macd_line, sig, macd_line - sig


def trend_quality_r2(
    closes: Sequence[float], i: int, span: int
) -> float | None:
    """Signed R^2 of an OLS fit of log(close) on time over the last `span` bars.

    Fits log(closes[i-span+1 .. i]) against t = 0..span-1 and returns
    R^2 * sign(slope): +1 for a perfectly smooth exponential uptrend, -1 for a
    perfectly smooth exponential decline, ~0 for noise or flatness. None if span<3,
    the window runs off the start, or any close in it is non-positive."""
    if span < 3 or i - span + 1 < 0:
        return None
    window = closes[i - span + 1 : i + 1]
    if any(c <= 0 for c in window):
        return None
    ys = [math.log(c) for c in window]
    xs = list(range(span))
    xbar = sum(xs) / span
    ybar = sum(ys) / span
    sxx = sum((x - xbar) ** 2 for x in xs)
    syy = sum((y - ybar) ** 2 for y in ys)
    sxy = sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys))
    if syy == 0 or sxx == 0:                # a flat (log-)series has no trend
        return 0.0
    r2 = (sxy * sxy) / (sxx * syy)
    sign = 1.0 if sxy > 0 else (-1.0 if sxy < 0 else 0.0)
    return r2 * sign


def ols_beta_alpha(
    y: Sequence[float], x: Sequence[float]
) -> tuple[float, float] | None:
    """Ordinary least squares of y on x, returning (slope, intercept).

    None if fewer than 2 points or x has zero variance."""
    n = len(x)
    if n < 2 or len(y) != n:
        return None
    xbar = sum(x) / n
    ybar = sum(y) / n
    sxx = sum((xi - xbar) ** 2 for xi in x)
    if sxx == 0:
        return None
    sxy = sum((xi - xbar) * (yi - ybar) for xi, yi in zip(x, y))
    slope = sxy / sxx
    intercept = ybar - slope * xbar
    return slope, intercept