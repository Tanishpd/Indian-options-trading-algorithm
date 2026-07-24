"""Walk-forward filter logic. The property that matters: a filter that separates
winners from losers in H1 is fit on H1 alone, then evaluated COLD on H2 — and when
the H1 relationship is reversed in H2 (the overfitting case this study exists to
catch), the filter's cold-H2 result is negative and worse than random.
"""
import random
from datetime import date

from optionsbot.research.walk_forward import (
    SPLIT, fit_threshold, keep, study)

H1DAY = date(2025, 1, 6)          # before SPLIT (2025-07-15)
H2DAY = date(2025, 8, 4)          # after SPLIT


def rec(d, net, rvol):
    # credit/trend/gap held constant so only the rvol filter discriminates.
    return dict(date=d, net=net, credit=100.0, rvol=rvol, trend=0.001, gap=0.001)


def test_keep_respects_direction_and_threshold():
    rows = [rec(H1DAY, 1, 0.001), rec(H1DAY, 1, 0.02)]
    assert len(keep(rows, "rvol", "le", 0.001)) == 1        # only the low-rvol day
    assert len(keep(rows, "rvol", "ge", 0.001)) == 2        # both are >= 0.001


def test_fit_threshold_picks_the_discriminating_cut():
    # 5 low-rvol winners, 5 high-rvol losers -> the Sharpe-max cut keeps the winners.
    train = ([rec(H1DAY, 1000, 0.001) for _ in range(5)]
             + [rec(H1DAY, -1000, 0.02) for _ in range(5)])
    thr = fit_threshold("rvol", "le", train)
    assert thr == 0.001
    assert all(r["net"] > 0 for r in keep(train, "rvol", "le", thr))


def test_overfit_filter_is_negative_and_worse_than_random_cold():
    # H1: low rvol -> win. H2: the relationship FLIPS (low rvol -> lose). A filter fit
    # on H1 therefore selects H2's losing days -> negative and below the random null.
    h1 = ([rec(H1DAY, 1000, 0.001) for _ in range(5)]
          + [rec(H1DAY, -1000, 0.02) for _ in range(5)])
    h2 = ([rec(H2DAY, -1000, 0.001) for _ in range(5)]
          + [rec(H2DAY, 1000, 0.02) for _ in range(5)])
    res, n_h2 = study(h1 + h2, random.Random(0))
    base_h2_net = res["base"][2]
    row = next(r for r in res["rows"] if r[0] == "rvol_low")
    _, h1_net, h2_net, k2, pct, _ = row
    assert h1_net > 0                       # looked great where it was fit
    assert h2_net < 0                       # negative on cold data
    assert h2_net < base_h2_net             # worse than trading every day
    assert pct < 50.0                       # worse than the median random day-drop
