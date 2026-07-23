"""Overfitting statistics. Every building block is pinned to a hand-computed or
analytically-known value; the selection metrics (CSCV/PBO, Reality Check) are
pinned on CONSTRUCTED fixtures where the right answer is known by construction:
one config that dominates in every block must give PBO ~ 0, pure noise must
give PBO ~ 0.5, a candidate that strictly beats the base must give a tiny
Reality-Check p, and one identical to the base a large p.
"""
import math
import random
import statistics

import pytest

from optionsbot.research.overfit_stats import (
    cscv_pbo, deflated_sharpe_ratio, expected_max_sharpe, normal_cdf,
    normal_ppf, probabilistic_sharpe_ratio, reality_check_pvalue,
    romano_wolf_pvalues, sharpe, skew_kurt)


# -- Normal distribution --------------------------------------------------

def test_normal_cdf_known_points():
    assert normal_cdf(0.0) == pytest.approx(0.5)
    # Phi(1.96) ~ 0.975, Phi(-1.96) ~ 0.025; symmetric about 0.
    assert normal_cdf(1.959963985) == pytest.approx(0.975, abs=1e-6)
    assert normal_cdf(-1.959963985) == pytest.approx(0.025, abs=1e-6)


def test_normal_ppf_known_quantiles():
    assert normal_ppf(0.5) == 0.0                       # exact by construction
    assert normal_ppf(0.975) == pytest.approx(1.959964, abs=1e-5)
    assert normal_ppf(0.025) == pytest.approx(-1.959964, abs=1e-5)
    # ppf is the inverse of cdf: round-trip a couple of interior points.
    for p in (0.1, 0.3, 0.8, 0.99):
        assert normal_cdf(normal_ppf(p)) == pytest.approx(p, abs=1e-8)


# -- Sharpe ---------------------------------------------------------------

def test_sharpe_hand_computed():
    # returns 0.01, 0.02, 0.03: mean 0.02; sample stdev sqrt((0.01^2+0.01^2)/2)
    # = 0.01; per-period Sharpe = 0.02 / 0.01 = 2.0.
    assert sharpe([0.01, 0.02, 0.03]) == pytest.approx(2.0)
    # Annualised by sqrt(periods_per_year): 2.0 * sqrt(4) = 4.0.
    assert sharpe([0.01, 0.02, 0.03], periods_per_year=4) == pytest.approx(4.0)


def test_sharpe_degenerate_is_nan():
    assert math.isnan(sharpe([0.01]))            # < 2 observations
    assert math.isnan(sharpe([0.02, 0.02, 0.02]))  # zero dispersion


# -- Higher moments -------------------------------------------------------

def test_skew_kurt_symmetric_fixture():
    # -2,-1,0,1,2: mean 0, m2 = (4+1+0+1+4)/5 = 2, m4 = (16+1+0+1+16)/5 = 6.8.
    # skew = m3/m2^1.5 = 0 (symmetric); kurt = m4/m2^2 = 6.8/4 = 1.7.
    skew, kurt = skew_kurt([-2, -1, 0, 1, 2])
    assert skew == pytest.approx(0.0, abs=1e-12)
    assert kurt == pytest.approx(1.7)


def test_skew_kurt_degenerate_defaults_to_normal():
    assert skew_kurt([1.0]) == (0.0, 3.0)
    assert skew_kurt([2.0, 2.0, 2.0]) == (0.0, 3.0)


# -- Probabilistic Sharpe -------------------------------------------------

def test_psr_is_half_when_sr_equals_benchmark():
    # sr - benchmark = 0 -> z = 0 -> Phi(0) = 0.5, regardless of moments.
    assert probabilistic_sharpe_ratio(0.1, 0.1, 100, 0.0, 3.0) == pytest.approx(0.5)


def test_psr_monotone_above_benchmark():
    # sr strictly above benchmark -> probability strictly above 0.5, and
    # increasing in the gap.
    lo = probabilistic_sharpe_ratio(0.15, 0.10, 100, 0.0, 3.0)
    hi = probabilistic_sharpe_ratio(0.25, 0.10, 100, 0.0, 3.0)
    assert 0.5 < lo < hi < 1.0


# -- Expected max Sharpe / Deflated Sharpe --------------------------------

def test_expected_max_sharpe_increases_with_trials():
    a = expected_max_sharpe(0.5, 2)
    b = expected_max_sharpe(0.5, 10)
    c = expected_max_sharpe(0.5, 100)
    assert 0.0 < a < b < c        # more configs tried -> higher bar

    # Scales linearly in the cross-trial SR dispersion.
    assert expected_max_sharpe(1.0, 10) == pytest.approx(2.0 * expected_max_sharpe(0.5, 10))


def test_deflated_sharpe_strong_vs_weak():
    # Strong per-period SR, long track, only a handful of trials -> passes.
    strong = deflated_sharpe_ratio(0.30, 0.10, 50, 200, 0.0, 3.0)
    # Weak SR, same everything -> nowhere near.
    weak = deflated_sharpe_ratio(0.02, 0.10, 50, 200, 0.0, 3.0)
    assert strong > 0.80
    assert weak < 0.05
    assert strong > weak

    # DSR is just PSR against the expected-max benchmark.
    bench = expected_max_sharpe(0.10, 50)
    assert deflated_sharpe_ratio(0.30, 0.10, 50, 200, 0.0, 3.0) == \
        pytest.approx(probabilistic_sharpe_ratio(0.30, bench, 200, 0.0, 3.0))


# -- CSCV / Probability of Backtest Overfitting ---------------------------

def test_cscv_pbo_dominant_config_is_zero():
    """One config beats every rival on both mean and Sharpe inside EVERY block,
    so the IS-best is always it and its OOS rank is always the top -> PBO 0."""
    T = 20
    dom = [0.10 + 0.001 * (t % 2) for t in range(T)]   # high mean, tiny vol
    r1 = [0.01 * ((-1) ** t) for t in range(T)]        # ~0 mean
    r2 = [0.02 + 0.02 * ((-1) ** t) for t in range(T)]
    r3 = [-0.01 + 0.01 * ((-1) ** t) for t in range(T)]
    out = cscv_pbo([dom, r1, r2, r3], n_blocks=4)
    assert out["n_splits"] == 6            # C(4, 2)
    assert out["pbo"] == pytest.approx(0.0)
    assert len(out["logits"]) == 6
    assert all(lo > 0 for lo in out["logits"])   # IS-best always above OOS median


def test_cscv_pbo_pure_noise_is_half_on_average():
    """With i.i.d. noise configs there is no persistent edge, so the IS-best
    lands on either side of the OOS median about equally. A single small matrix
    is itself noisy, so pin the AVERAGE PBO over many independent matrices,
    which converges to ~0.5."""
    master = random.Random(0)
    pbos = []
    for _ in range(80):
        mat = [[master.gauss(0.0, 1.0) for _ in range(60)] for _ in range(10)]
        pbos.append(cscv_pbo(mat, n_blocks=6)["pbo"])
    assert statistics.mean(pbos) == pytest.approx(0.5, abs=0.08)


def test_cscv_pbo_rejects_odd_blocks():
    with pytest.raises(ValueError):
        cscv_pbo([[0.0] * 10, [1.0] * 10], n_blocks=5)


# -- White's Reality Check ------------------------------------------------

def test_reality_check_strict_domination_tiny_p():
    """Candidates that beat the base by a fixed margin at every date cannot be
    explained by luck: the recentered bootstrap stat never reaches the observed
    one, so p is the floor 1/(n_boot+1)."""
    rng = random.Random(1)
    base = [rng.gauss(0.0, 1.0) for _ in range(30)]
    cands = [[b + 0.5 for b in base], [b + 0.3 for b in base]]
    p = reality_check_pvalue(cands, base, n_boot=2000, seed=7)
    assert p == pytest.approx(1.0 / 2001.0, abs=1e-9)
    assert p < 0.01


def test_reality_check_identical_to_base_large_p():
    """A candidate identical to the base has zero differential everywhere; the
    observed and every bootstrap stat are 0, so every draw ties -> p = 1.0."""
    rng = random.Random(2)
    base = [rng.gauss(0.0, 1.0) for _ in range(30)]
    p = reality_check_pvalue([list(base)], base, n_boot=2000, seed=7)
    assert p == pytest.approx(1.0)
    assert p > 0.5


def test_reality_check_is_deterministic_in_seed():
    rng = random.Random(3)
    base = [rng.gauss(0.0, 1.0) for _ in range(40)]
    cands = [[b + 0.05 * rng.gauss(0, 1) for b in base] for _ in range(4)]
    p1 = reality_check_pvalue(cands, base, seed=123)
    p2 = reality_check_pvalue(cands, base, seed=123)
    assert p1 == p2

def _rw_tstats(cands, base):
    """Studentised observed statistics, computed exactly as the function does,
    so tests can order candidates by the same key the stepdown uses."""
    T = len(base)
    out = []
    for c in cands:
        f = [c[i] - base[i] for i in range(T)]
        dbar = statistics.mean(f)
        sd = statistics.stdev(f) if len(f) >= 2 else 0.0
        sd = sd if sd > 0.0 else 1e-12
        out.append(math.sqrt(T) * dbar / sd)
    return out


def test_romano_wolf_all_identical_all_large():
    """Every candidate identical to the base: the differential is zero
    everywhere, so every observed and every bootstrap statistic is 0. At each
    step 0 >= 0 holds on every draw, so all adjusted p-values are 1.0 (well
    above 0.5) -- nothing is flagged as a real edge."""
    rng = random.Random(4)
    base = [rng.gauss(0.0, 1.0) for _ in range(40)]
    cands = [list(base), list(base), list(base)]
    padj = romano_wolf_pvalues(cands, base, n_boot=2000, seed=0)
    assert len(padj) == 3
    assert all(p > 0.5 for p in padj)
    assert all(p == pytest.approx(1.0) for p in padj)


def test_romano_wolf_single_strong_isolated():
    """One candidate beats the base by a fixed positive margin at every date
    (constant differential -> zero dispersion -> its studentised statistic is
    enormous and never approached by the recentred bootstrap), the other two
    are identical to the base. The strong one must get a tiny adjusted p; the
    two null ones stay large. FWER control does NOT wash out a genuinely
    dominant strategy."""
    rng = random.Random(5)
    base = [rng.gauss(0.0, 1.0) for _ in range(40)]
    strong = [b + 0.5 for b in base]
    cands = [list(base), strong, list(base)]   # strong is index 1
    padj = romano_wolf_pvalues(cands, base, n_boot=3000, seed=0)
    assert padj[1] < 0.05
    assert padj[0] > 0.5
    assert padj[2] > 0.5


def test_romano_wolf_monotone_along_tstat_order():
    """Adjusted p-values are non-decreasing when candidates are taken in
    descending order of their observed statistic -- the stepdown clamp
    guarantees it regardless of the underlying data."""
    rng = random.Random(6)
    base = [rng.gauss(0.0, 1.0) for _ in range(50)]
    # A spread of edges: strong, mild, none, and a slightly negative one.
    cands = [
        [b + 0.4 + 0.05 * rng.gauss(0, 1) for b in base],
        [b + 0.1 + 0.05 * rng.gauss(0, 1) for b in base],
        [b + 0.05 * rng.gauss(0, 1) for b in base],
        [b - 0.2 + 0.05 * rng.gauss(0, 1) for b in base],
    ]
    padj = romano_wolf_pvalues(cands, base, n_boot=2000, seed=0)
    order = sorted(range(len(cands)), key=lambda j: _rw_tstats(cands, base)[j],
                   reverse=True)
    ordered = [padj[j] for j in order]
    assert all(a <= b + 1e-12 for a, b in zip(ordered, ordered[1:]))


def test_romano_wolf_two_strong_both_flagged():
    """Two candidates each dominate the base by a fixed margin; both should be
    flagged (tiny adjusted p) even though they compete inside the same family,
    and the lone null candidate stays large."""
    rng = random.Random(7)
    base = [rng.gauss(0.0, 1.0) for _ in range(40)]
    cands = [[b + 0.5 for b in base], [b + 0.3 for b in base], list(base)]
    padj = romano_wolf_pvalues(cands, base, n_boot=3000, seed=0)
    assert padj[0] < 0.05
    assert padj[1] < 0.05
    assert padj[2] > 0.5


def test_romano_wolf_is_deterministic_in_seed():
    rng = random.Random(8)
    base = [rng.gauss(0.0, 1.0) for _ in range(45)]
    cands = [[b + 0.1 * rng.gauss(0, 1) for b in base] for _ in range(5)]
    p1 = romano_wolf_pvalues(cands, base, n_boot=1500, seed=99)
    p2 = romano_wolf_pvalues(cands, base, n_boot=1500, seed=99)
    assert p1 == p2
