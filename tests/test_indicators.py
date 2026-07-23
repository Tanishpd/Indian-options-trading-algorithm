"""Closes-only indicator helpers, each pinned to a hand-computed literal.

House style (see tests/test_momentum.py): show the arithmetic in a comment, then
assert it. Every function's None/too-short branch is covered too, because the
no-look-ahead contract is exactly what these guards enforce.
"""
import math

import pytest

from optionsbot.data.equity import Series
from optionsbot.research.indicators import (
    dist_from_sma,
    downside_deviation,
    ema,
    macd,
    ols_beta_alpha,
    realized_vol,
    roc,
    skip_month_return,
    sma,
    sma_slope,
    trend_quality_r2,
    wma,
)


# -- sma ------------------------------------------------------------------

def test_sma_hand_computed():
    c = [1.0, 2.0, 3.0, 4.0]
    assert sma(c, 3, 2) == pytest.approx(3.5)      # (3+4)/2
    assert sma(c, 3, 4) == pytest.approx(2.5)      # (1+2+3+4)/4
    assert sma(c, 0, 1) == pytest.approx(1.0)      # single-bar window


def test_sma_too_short_is_none():
    c = [1.0, 2.0, 3.0, 4.0]
    assert sma(c, 0, 2) is None                    # i-n+1 = -1 < 0
    assert sma(c, 2, 0) is None                    # n<=0


# -- ema ------------------------------------------------------------------

def test_ema_seed_then_one_step():
    c = [2.0, 4.0, 6.0]
    # n=2, alpha=2/3. seed at index 1 = SMA of first 2 = (2+4)/2 = 3.
    assert ema(c, 1, 2) == pytest.approx(3.0)
    # step to index 2: 2/3*6 + 1/3*3 = 4 + 1 = 5.
    assert ema(c, 2, 2) == pytest.approx(5.0)


def test_ema_too_short_is_none():
    c = [2.0, 4.0, 6.0]
    assert ema(c, 0, 2) is None                    # fewer than n bars up to i (i<n-1)
    assert ema(c, 2, 0) is None                    # n<=0


# -- wma ------------------------------------------------------------------

def test_wma_hand_computed():
    c = [1.0, 2.0, 3.0]
    # weights 1,2,3 (newest heaviest): (1*1 + 2*2 + 3*3)/(1+2+3) = 14/6.
    assert wma(c, 2, 3) == pytest.approx(14.0 / 6.0)
    # n=2 at i=2: (1*2 + 2*3)/3 = 8/3.
    assert wma(c, 2, 2) == pytest.approx(8.0 / 3.0)


def test_wma_too_short_is_none():
    assert wma([1.0, 2.0], 0, 2) is None


# -- sma_slope ------------------------------------------------------------

def test_sma_slope_hand_computed():
    c = [1.0, 2.0, 3.0, 4.0]
    # sma(3,2)=3.5, sma(2,2)=2.5 -> 3.5/2.5 - 1 = 0.4.
    assert sma_slope(c, 3, 2, k=1) == pytest.approx(0.4)


def test_sma_slope_none_when_prev_undefined():
    c = [1.0, 2.0, 3.0, 4.0]
    # sma(0,2) is undefined -> whole slope None.
    assert sma_slope(c, 1, 2, k=1) is None


# -- dist_from_sma --------------------------------------------------------

def test_dist_from_sma_hand_computed():
    c = [1.0, 2.0, 3.0, 4.0]
    # closes[3]/sma(3,2) - 1 = 4/3.5 - 1 = 1/7.
    assert dist_from_sma(c, 3, 2) == pytest.approx(4.0 / 3.5 - 1.0)


def test_dist_from_sma_none_when_sma_undefined():
    assert dist_from_sma([1.0, 2.0], 0, 2) is None


# -- roc ------------------------------------------------------------------

def test_roc_hand_computed():
    c = [100.0, 110.0, 121.0]
    assert roc(c, 2, 2) == pytest.approx(0.21)     # 121/100 - 1


def test_roc_none_branches():
    assert roc([100.0, 110.0], 1, 2) is None       # i-n = -1 < 0
    assert roc([0.0, 1.0, 2.0], 2, 2) is None      # reference close 0 (<=0)


# -- skip_month_return (12-1 momentum) ------------------------------------

def test_skip_month_return_hand_computed():
    c = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
    # long=4, skip=1 at i=5: closes[4]/closes[1] - 1 = 104/101 - 1.
    assert skip_month_return(c, 5, long=4, skip=1) == pytest.approx(104.0 / 101.0 - 1.0)


def test_skip_month_return_too_short_is_none():
    c = [100.0, 101.0, 102.0, 103.0]
    assert skip_month_return(c, 3, long=4, skip=1) is None   # i-long = -1 < 0


# -- realized_vol (matches Series.daily_vol on a shared fixture) ----------

FIXTURE = [100.0, 110.0, 99.0]      # returns +0.10 then -0.10


def test_realized_vol_matches_daily_vol():
    s = Series(symbol="X", dates=_days(3), closes=tuple(FIXTURE))
    # sample stdev of [+0.1, -0.1] = sqrt((0.1^2 + 0.1^2)/1) = 0.14142135...
    assert realized_vol(FIXTURE, 2, 2, annualize=False) == pytest.approx(0.14142135, abs=1e-6)
    # identical to the Series helper on the same window.
    assert realized_vol(FIXTURE, 2, 2, annualize=False) == pytest.approx(s.daily_vol(2, 2))


def test_realized_vol_annualized():
    # non-annualised 0.14142135... times sqrt(252).
    expected = 0.1414213562373095 * math.sqrt(252)
    assert realized_vol(FIXTURE, 2, 2) == pytest.approx(expected)


def test_realized_vol_too_short_is_none():
    assert realized_vol([100.0], 0, 2) is None     # zero returns available
    assert realized_vol([100.0, 110.0], 1, 1) is None  # only 1 return, need >=2


# -- downside_deviation ---------------------------------------------------

def test_downside_deviation_hand_computed():
    # returns [+0.1, -0.1]; min(r,0)^2 = [0, 0.01]; mean = 0.005; sqrt = 0.0707106781.
    assert downside_deviation(FIXTURE, 2, 2, annualize=False) == pytest.approx(
        math.sqrt(0.005))


def test_downside_deviation_annualized():
    expected = math.sqrt(0.005) * math.sqrt(252)
    assert downside_deviation(FIXTURE, 2, 2) == pytest.approx(expected)


def test_downside_deviation_one_return_ok_none_when_zero():
    # a single return is enough (>=1); [+0.1] has no downside -> 0.0.
    assert downside_deviation([100.0, 110.0], 1, 1, annualize=False) == pytest.approx(0.0)
    assert downside_deviation([100.0], 0, 2) is None   # zero returns -> None


# -- macd -----------------------------------------------------------------

def test_macd_hand_computed():
    # fast=2, slow=3, signal=2 on [10,11,12,13,14].
    # ema(2): seed idx1=(10+11)/2=10.5; idx2=2/3*12+1/3*10.5=11.5;
    #         idx3=2/3*13+1/3*11.5=12.5; idx4=2/3*14+1/3*12.5=13.5.
    # ema(3): seed idx2=(10+11+12)/3=11; idx3=0.5*13+0.5*11=12; idx4=0.5*14+0.5*12=13.
    # macd_line at idx2,3,4 = 0.5, 0.5, 0.5 (constant).
    # signal(2): seed = SMA(first 2 macd)=0.5; stays 0.5. hist = 0.
    c = [10.0, 11.0, 12.0, 13.0, 14.0]
    line, sig, hist = macd(c, 4, fast=2, slow=3, signal=2)
    assert line == pytest.approx(0.5)
    assert sig == pytest.approx(0.5)
    assert hist == pytest.approx(0.0)


def test_macd_none_until_signal_seedable():
    c = [10.0, 11.0, 12.0, 13.0, 14.0]
    # slow=3, signal=2 -> first defined index is slow+signal-2 = 3.
    assert macd(c, 2, fast=2, slow=3, signal=2) is None    # only 1 macd value, can't seed
    assert macd(c, 3, fast=2, slow=3, signal=2) is not None


# -- trend_quality_r2 -----------------------------------------------------

def test_trend_quality_perfect_exponential_uptrend_is_plus_one():
    # log(close) is exactly linear & increasing -> R^2=1, sign(+) -> +1.0.
    c = [math.exp(0.1 * t) for t in range(6)]
    assert trend_quality_r2(c, 5, 6) == pytest.approx(1.0)


def test_trend_quality_perfect_exponential_decline_is_minus_one():
    # log(close) linear & decreasing -> R^2=1, sign(-) -> -1.0.
    c = [math.exp(-0.1 * t) for t in range(6)]
    assert trend_quality_r2(c, 5, 6) == pytest.approx(-1.0)


def test_trend_quality_flat_is_zero():
    c = [50.0, 50.0, 50.0, 50.0]
    assert trend_quality_r2(c, 3, 4) == pytest.approx(0.0)   # no variance in log(y)


def test_trend_quality_none_branches():
    c = [1.0, 2.0, 3.0]
    assert trend_quality_r2(c, 2, 2) is None                 # span < 3
    assert trend_quality_r2(c, 1, 3) is None                 # window runs off the start
    assert trend_quality_r2([1.0, 0.0, 3.0], 2, 3) is None   # a close <= 0


# -- ols_beta_alpha -------------------------------------------------------

def test_ols_recovers_known_line():
    x = [1.0, 2.0, 3.0, 4.0]
    y = [3.0, 5.0, 7.0, 9.0]      # y = 2x + 1 exactly
    slope, intercept = ols_beta_alpha(y, x)
    assert slope == pytest.approx(2.0)
    assert intercept == pytest.approx(1.0)


def test_ols_none_branches():
    assert ols_beta_alpha([1.0], [1.0]) is None              # fewer than 2 points
    assert ols_beta_alpha([1.0, 2.0, 3.0], [2.0, 2.0, 2.0]) is None  # var(x) = 0


# -- helpers --------------------------------------------------------------

from datetime import date, timedelta


def _days(n: int):
    d0 = date(2025, 1, 1)
    return tuple(d0 + timedelta(days=k) for k in range(n))