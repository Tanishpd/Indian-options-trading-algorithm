"""Overfitting statistics — the numbers that separate a real edge from a
data-mined one.

The whole project runs on one uncomfortable premise (CLAUDE.md rule 5): every
published performance claim is unverified marketing until it survives an
adversarial test, and the most dangerous failure mode is a strategy that looks
great only because it was the best of many tried. These are the tools that put
a probability on that.

  - probabilistic_sharpe_ratio / deflated_sharpe_ratio (Bailey & Lopez de
    Prado): what is the chance the true Sharpe exceeds a benchmark, once you
    correct for track-record length, non-normal returns, AND the number of
    configurations you tried? DSR > 0.95 is the go/no-go.
  - cscv_pbo (Combinatorially-Symmetric Cross-Validation): the Probability of
    Backtest Overfitting — how often the in-sample-best config lands below the
    median out-of-sample. ~0.5 means your selection is noise.
  - reality_check_pvalue (White's Reality Check, stationary bootstrap): is the
    best candidate really better than a benchmark, or is it the max of a lot of
    draws?

Pure stdlib: math, statistics, random, itertools. No numpy by design — the repo
is deliberately dependency-light, and every formula here is short enough to read.
"""
from __future__ import annotations

import math
import statistics
from itertools import combinations
from random import Random
from typing import Sequence

_EULER_MASCHERONI = 0.5772156649015329


# -- Normal distribution --------------------------------------------------

def normal_cdf(z: float) -> float:
    """Standard-normal CDF, Phi(z) = 0.5*(1 + erf(z/sqrt(2)))."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


# Acklam / Beasley-Springer rational approximation to the inverse normal CDF.
# Relative error < 1.15e-9 across (0, 1); accurate enough that a Halley
# refinement is unnecessary for our purposes.
_A = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
      1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
_B = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
      6.680131188771972e+01, -1.328068155288572e+01)
_C = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
      -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
_D = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
      3.754408661907416e+00)
_P_LOW = 0.02425
_P_HIGH = 1.0 - _P_LOW


def normal_ppf(p: float) -> float:
    """Inverse standard-normal CDF (quantile function).

    ppf(0.5) == 0 exactly; ppf(0.975) ~= 1.959964. Endpoints return +/-inf.
    """
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    if p < _P_LOW:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / \
               ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0)
    if p <= _P_HIGH:
        q = p - 0.5
        r = q * q
        return (((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5]) * q / \
               (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1.0)
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / \
           ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0)


# -- Sharpe ---------------------------------------------------------------

def sharpe(returns: Sequence[float], periods_per_year: int | None = None) -> float:
    """Sharpe ratio: mean / sample-stdev (ddof=1) of the return series.

    Per-period by default; if periods_per_year is given, annualised by
    multiplying by sqrt(periods_per_year). nan when fewer than 2 observations
    or the series has zero dispersion.
    """
    n = len(returns)
    if n < 2:
        return math.nan
    sd = statistics.stdev(returns)
    if sd == 0.0:
        return math.nan
    sr = statistics.mean(returns) / sd
    if periods_per_year is not None:
        sr *= math.sqrt(periods_per_year)
    return sr


# -- Higher moments -------------------------------------------------------

def skew_kurt(returns: Sequence[float]) -> tuple[float, float]:
    """Sample skewness and NON-excess kurtosis (normal -> 3.0).

    Uses the moment estimators m3/m2^1.5 and m4/m2^2 with population central
    moments, matching the inputs Bailey & Lopez de Prado feed to PSR/DSR. A
    zero-dispersion or too-short series returns the normal defaults (0.0, 3.0)
    so downstream PSR stays well-defined.
    """
    n = len(returns)
    if n < 2:
        return 0.0, 3.0
    mean = statistics.mean(returns)
    m2 = sum((x - mean) ** 2 for x in returns) / n
    if m2 == 0.0:
        return 0.0, 3.0
    m3 = sum((x - mean) ** 3 for x in returns) / n
    m4 = sum((x - mean) ** 4 for x in returns) / n
    skew = m3 / (m2 ** 1.5)
    kurt = m4 / (m2 * m2)
    return skew, kurt


# -- Probabilistic / Deflated Sharpe --------------------------------------

def probabilistic_sharpe_ratio(sr: float, sr_benchmark: float, n_obs: int,
                               skew: float, kurt: float) -> float:
    """Probability the true Sharpe exceeds sr_benchmark (Bailey & LdP).

    sr and sr_benchmark are PER-PERIOD (non-annualised); kurt is non-excess
    (normal = 3). Returns a probability in (0, 1). When sr == sr_benchmark the
    result is exactly 0.5.
    """
    arg = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr * sr
    if arg <= 0.0:
        arg = 1e-12
    z = (sr - sr_benchmark) * math.sqrt(n_obs - 1) / math.sqrt(arg)
    return normal_cdf(z)


def expected_max_sharpe(sr_std_across_trials: float, n_trials: int) -> float:
    """Expected maximum Sharpe under the null that every trial has true SR 0.

    SR0 = sr_std * ((1-g)*Z(1 - 1/N) + g*Z(1 - 1/(N*e))), g = Euler-Mascheroni,
    Z = normal_ppf, N = n_trials (Bailey & Lopez de Prado). Grows with N: more
    tries, higher the best-by-luck Sharpe you must clear.
    """
    g = _EULER_MASCHERONI
    n = n_trials
    return sr_std_across_trials * (
        (1.0 - g) * normal_ppf(1.0 - 1.0 / n)
        + g * normal_ppf(1.0 - 1.0 / (n * math.e))
    )


def deflated_sharpe_ratio(sr: float, sr_std_across_trials: float, n_trials: int,
                          n_obs: int, skew: float, kurt: float) -> float:
    """Deflated Sharpe Ratio: PSR against the expected-max-Sharpe benchmark.

    This is the go/no-go number. > 0.95 means the observed Sharpe survives the
    multiple-testing correction for having tried n_trials configurations.
    """
    benchmark = expected_max_sharpe(sr_std_across_trials, n_trials)
    return probabilistic_sharpe_ratio(sr, benchmark, n_obs, skew, kurt)


# -- CSCV / Probability of Backtest Overfitting ---------------------------

def _subset_metric(vec: Sequence[float], idxs: Sequence[int], metric: str) -> float:
    xs = [vec[t] for t in idxs]
    if metric == "mean":
        return statistics.mean(xs)
    # metric == 'sharpe' (per-period)
    if len(xs) < 2:
        return float("-inf")
    sd = statistics.stdev(xs)
    if sd == 0.0:
        return 0.0
    return statistics.mean(xs) / sd


def _contiguous_blocks(t: int, n_blocks: int) -> list[list[int]]:
    base = t // n_blocks
    rem = t % n_blocks
    blocks: list[list[int]] = []
    start = 0
    for i in range(n_blocks):
        size = base + (1 if i < rem else 0)
        blocks.append(list(range(start, start + size)))
        start += size
    return blocks


def cscv_pbo(matrix: Sequence[Sequence[float]], n_blocks: int = 10,
             metric: str = "sharpe") -> dict:
    """Combinatorially-Symmetric Cross-Validation -> Probability of Backtest
    Overfitting.

    matrix: N config return-vectors, each length T on the same clock. The T
    time indices are split into n_blocks contiguous (near-)equal blocks. For
    every way to pick n_blocks/2 blocks as in-sample (rest OOS): rank the
    configs by IS metric, take the IS-best config n*, find its OOS rank r
    (1..N, higher metric = higher rank), relative rank w = r/(N+1), logit =
    ln(w/(1-w)). PBO is the fraction of splits with logit < 0 (IS-best lands
    below the OOS median).

    Returns {'pbo', 'logits', 'n_splits'}.
    """
    n_configs = len(matrix)
    if n_configs == 0:
        return {"pbo": math.nan, "logits": [], "n_splits": 0}
    t = len(matrix[0])
    if n_blocks % 2 != 0:
        raise ValueError("n_blocks must be even")
    if t < n_blocks:
        raise ValueError("need at least n_blocks time periods")

    blocks = _contiguous_blocks(t, n_blocks)
    logits: list[float] = []
    for is_block_ids in combinations(range(n_blocks), n_blocks // 2):
        is_set = set(is_block_ids)
        is_idx = [i for b in is_block_ids for i in blocks[b]]
        oos_idx = [i for b in range(n_blocks) if b not in is_set for i in blocks[b]]

        is_scores = [_subset_metric(vec, is_idx, metric) for vec in matrix]
        # IS-best config (first on ties).
        n_star = max(range(n_configs), key=lambda c: is_scores[c])

        oos_scores = [_subset_metric(vec, oos_idx, metric) for vec in matrix]
        star_val = oos_scores[n_star]
        # rank 1..N, higher metric -> higher rank; ties do not inflate.
        r = 1 + sum(1 for v in oos_scores if v < star_val)
        w = r / (n_configs + 1)
        logits.append(math.log(w / (1.0 - w)))

    pbo = sum(1 for lo in logits if lo < 0.0) / len(logits)
    return {"pbo": pbo, "logits": logits, "n_splits": len(logits)}


# -- White's Reality Check (stationary bootstrap) -------------------------

def _stationary_path(rng: Random, t: int, block_len: float) -> list[int]:
    """Politis-Romano stationary-bootstrap index path of length T.

    Start at a random index; each step, with probability 1/block_len jump to a
    fresh random start, else advance by one (wrapping). Mean block length is
    block_len.
    """
    p_jump = 1.0 / block_len
    path: list[int] = []
    pos = rng.randrange(t)
    for _ in range(t):
        path.append(pos)
        if rng.random() < p_jump:
            pos = rng.randrange(t)
        else:
            pos = (pos + 1) % t
    return path


def reality_check_pvalue(candidate_matrix: Sequence[Sequence[float]],
                         base_vector: Sequence[float], block_len: float = 6.0,
                         n_boot: int = 2000, seed: int = 0,
                         studentize: bool = True) -> float:
    """White's Reality Check p-value via the stationary bootstrap.

    Tests H0: the best of the K candidates is no better than the base
    (benchmark). Performance differential f[k][t] = candidate[k][t] -
    base[t] (higher = better). The statistic is
        V = max_k sqrt(T) * d_bar[k] / w[k]
    where d_bar[k] = mean_t f[k][t] and w[k] = stdev(f[k]) (studentised; 1 if
    not, and a zero stdev is guarded to 1). Each bootstrap draw recenters by
    subtracting the original d_bar[k] (White's centering); p is the recentered
    exceedance rate, (#{V*_b >= V} + 1) / (n_boot + 1). Deterministic in seed.
    """
    k = len(candidate_matrix)
    t = len(base_vector)
    if k == 0 or t == 0:
        return 1.0

    f = [[candidate_matrix[j][i] - base_vector[i] for i in range(t)] for j in range(k)]
    d_bar = [statistics.mean(f[j]) for j in range(k)]
    if studentize:
        w = []
        for j in range(k):
            sd = statistics.stdev(f[j]) if t >= 2 else 0.0
            w.append(sd if sd > 0.0 else 1.0)
    else:
        w = [1.0] * k

    sqrt_t = math.sqrt(t)
    v_obs = max(sqrt_t * d_bar[j] / w[j] for j in range(k))

    rng = Random(seed)
    count = 0
    for _ in range(n_boot):
        path = _stationary_path(rng, t, block_len)
        v_star = float("-inf")
        for j in range(k):
            fj = f[j]
            boot_mean = sum(fj[i] for i in path) / t
            stat = sqrt_t * (boot_mean - d_bar[j]) / w[j]
            if stat > v_star:
                v_star = stat
        if v_star >= v_obs:
            count += 1
    return (count + 1) / (n_boot + 1)