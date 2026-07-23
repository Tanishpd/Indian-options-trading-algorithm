"""Pre-registration integrity + the runner's pure windowing helpers.

The integrity test enforces the discipline in code: exactly 20 configs, base
first, unique names, every candidate carrying an ex-ante mechanism. If someone
appends a 21st config after seeing results, this test is where it should hurt.
"""
from datetime import date, timedelta

from optionsbot.data.equity import Series
from optionsbot.research.search_configs import PREREGISTERED
from optionsbot.research.run_indicator_search import (
    monthly_in_window, align_matrix, fetch_windows, index_covers_window)


def test_preregistration_is_frozen_and_well_formed():
    assert len(PREREGISTERED) == 20                       # K is fixed
    assert PREREGISTERED[0].name == "base"                # column 0 is the benchmark
    names = [c.name for c in PREREGISTERED]
    assert len(set(names)) == 20                          # unique
    assert all(c.mechanism.strip() for c in PREREGISTERED)  # every config justified
    # Base is the real momentum config, not a toy.
    b = PREREGISTERED[0]
    assert (b.top_n, b.lookback_short, b.lookback_long) == (30, 126, 252)
    assert b.regime_mode == "price_sma" and b.regime_sma == 200
    # The negative controls are present — the harness must be able to reject.
    assert {"ctrl_no_regime", "ctrl_top50"} <= set(names)
    valid_ranks = {"base", "skip_month", "residual", "trend_quality", "downside"}
    assert all(c.rank_mode in valid_ranks for c in PREREGISTERED)


def test_monthly_in_window_lo_exclusive_hi_inclusive():
    m = [(date(2022, 8, 31), 0.01), (date(2022, 9, 30), 0.02),
         (date(2022, 10, 31), 0.03), (date(2025, 7, 31), 0.04)]
    # lo=2022-09-30 exclusive drops the 09-30 mark; hi=2025-06-30 drops the holdout.
    assert monthly_in_window(m, date(2022, 9, 30), date(2025, 6, 30)) == [0.03]
    assert monthly_in_window(m, date(2022, 9, 30), None) == [0.03, 0.04]


def test_fetch_windows_are_contiguous_with_no_gap():
    """Regression guard for the index-cache hole: consecutive fetch windows must
    abut exactly (next lo = prev hi + 1 day), covering the whole range."""
    wins = fetch_windows(date(2016, 1, 1), date(2026, 7, 23), years=5)
    assert wins[0][0] == date(2016, 1, 1)
    assert wins[-1][1] == date(2026, 7, 23)
    for (_, hi), (lo2, _) in zip(wins, wins[1:]):
        assert lo2 == hi + timedelta(days=1)          # no gap, no overlap
    # The original bug produced a 5-year hole; assert full coverage instead.
    assert all(a <= b for a, b in wins)


def test_index_coverage_guard_rejects_a_holey_index():
    ds = ([date(2020, 1, 1) + timedelta(days=i) for i in range(400)]        # 2020-21
          + [date(2026, 1, 1) + timedelta(days=i) for i in range(60)])      # 2026 only
    holey = Series("IDX", tuple(ds), tuple(100.0 + i for i in range(len(ds))))
    # Nothing in 2022-09..2025-07 -> must be rejected.
    assert not index_covers_window(holey, date(2022, 9, 30), date(2025, 7, 1))
    full = [date(2018, 1, 1) + timedelta(days=i) for i in range(3000)]
    good = Series("IDX", tuple(full), tuple(100.0 + i for i in range(len(full))))
    assert index_covers_window(good, date(2022, 9, 30), date(2025, 7, 1))


def test_align_matrix_equal_length_rows_on_common_dates():
    monthlies = {
        "a": [(date(2023, 1, 31), 0.1), (date(2023, 2, 28), 0.2), (date(2023, 3, 31), 0.3)],
        "b": [(date(2023, 2, 28), 0.9), (date(2023, 3, 31), 0.8)],   # missing Jan
    }
    names, mat = align_matrix(monthlies, ["a", "b"], date(2022, 1, 1), None)
    assert names == ["a", "b"]
    assert len(mat[0]) == len(mat[1]) == 2                # common dates: Feb, Mar
    assert mat[0] == [0.2, 0.3] and mat[1] == [0.9, 0.8]
