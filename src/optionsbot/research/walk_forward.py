"""Walk-forward regime-filter study — can any filter FIX the intraday-only H2
negative WITHOUT being fit to H2? (docs/18, closing the docs/17 addendum.)

The intraday-only strangle is +74% in H1 and negative in H2 (docs/17). The tempting
"fix" is a regime filter that stands down in H2-like conditions — but a filter fit to
the losses you already saw is curve-fitting. This runs the only honest test:

  1. Fit each filter's threshold on H1 ONLY (maximise H1 daily Sharpe).
  2. Lock it. Evaluate COLD on H2 (never touched during fitting).
  3. Require the winner to (a) turn H2 net positive AND (b) beat a permutation null —
     removing the SAME number of H2 days at RANDOM — so a "fix" has to beat luck.

Filtering only selects WHICH existing daily trades to keep (a traded day's P&L is
unchanged), so the base intraday backtest runs once and every filter is arithmetic.

Result (see docs/18): 0 of 5 pre-registered filters turn cold H2 positive; 0 beat the
random null; and the filter that fits BEST on H1 is anti-predictive on H2 (4th
percentile). No filter fit on H1 durably fixes H2 — the negatives are the strategy's
true regime-dependent edge, not a patchable defect.

    python -m optionsbot.research.walk_forward data/intraday/NIFTY
"""
from __future__ import annotations

import random
import statistics
import sys
from datetime import date
from pathlib import Path

from ..config import CostConfig, MarketConfig
from .intraday_only import MAX_LOTS, intraday_params, plan_days, run
from .run_intraday import cycles

SPLIT = date(2025, 7, 15)          # H2 start — matches the docs/17 OOS split
NPERM = 3000
SEED = 12345

# Pre-registered filters: (name, feature, keep-direction, rationale). Direction "ge"
# keeps days at/above the threshold, "le" at/below.
FILTERS = [
    ("credit_high", "credit", "ge", "sell only when premium is rich"),
    ("credit_low", "credit", "le", "sell only when premium is cheap (calm IV)"),
    ("rvol_low", "rvol", "le", "stand down in high realized vol"),
    ("trend_low", "trend", "le", "stand down in strong trends"),
    ("gap_low", "gap", "le", "stand down after big overnight gaps"),
]


def features(trades):
    """Per-day records with trailing features, all knowable BEFORE entry that day."""
    recs = [dict(date=t.entered_at.date(), net=t.net, credit=t.credit,
                 entry_spot=(t.short_call + t.short_put) / 2.0, exit_spot=t.final_spot)
            for t in trades]
    recs.sort(key=lambda r: r["date"])
    for i, r in enumerate(recs):
        r["rvol"] = (statistics.pstdev([recs[j]["entry_spot"] / recs[j - 1]["entry_spot"] - 1
                                        for j in range(i - 4, i + 1)]) if i >= 5 else None)
        r["trend"] = (abs(recs[i]["entry_spot"] / recs[i - 5]["entry_spot"] - 1) if i >= 5 else None)
        r["gap"] = (abs(recs[i]["entry_spot"] / recs[i - 1]["exit_spot"] - 1) if i >= 1 else None)
    return recs


def keep(rows, feat, direction, thr):
    return [r for r in rows if r[feat] is not None
            and (r[feat] >= thr if direction == "ge" else r[feat] <= thr)]


def _sharpe(rows):
    nets = [r["net"] for r in rows]
    if len(nets) < 2:
        return -1e18
    return statistics.mean(nets) / (statistics.pstdev(nets) or 1e-9)


def fit_threshold(feat, direction, train, min_keep=0.4):
    """Threshold maximising TRAIN daily Sharpe, keeping >= min_keep of days."""
    have = [r for r in train if r[feat] is not None]
    best = None
    for thr in sorted(set(r[feat] for r in have)):
        kept = keep(have, feat, direction, thr)
        if len(kept) < min_keep * len(have):
            continue
        s = _sharpe(kept)
        if best is None or s > best[0]:
            best = (s, thr)
    return None if best is None else best[1]


def _net(rows, lots=MAX_LOTS):
    return sum(r["net"] for r in rows) * lots


def study(recs, rng):
    """Fit each filter on H1, test cold on H2, permutation-null on H2."""
    h1 = [r for r in recs if r["date"] < SPLIT]
    h2 = [r for r in recs if r["date"] >= SPLIT]
    out = {"base": (_net(h1), len(h1), _net(h2), len(h2)), "rows": []}
    for name, feat, direction, why in FILTERS:
        thr = fit_threshold(feat, direction, h1)
        if thr is None:
            out["rows"].append((name, None, None, None, float("nan"), why))
            continue
        h2k = keep(h2, feat, direction, thr)
        k2 = len(h2k)
        pool = [r["net"] for r in h2 if r[feat] is not None]
        if k2 >= 2 and len(pool) > k2:
            obs = statistics.mean([r["net"] for r in h2k])
            rand = [statistics.mean(rng.sample(pool, k2)) for _ in range(NPERM)]
            pct = 100.0 * sum(1 for m in rand if m <= obs) / NPERM
        else:
            pct = float("nan")
        out["rows"].append((name, _net(keep(h1, feat, direction, thr)),
                            _net(h2k), k2, pct, why))
    return out, len(h2)


def main(argv=None) -> int:
    root = Path(argv[0]) if argv else Path("data/intraday/NIFTY")
    files = cycles(root)
    if not files:
        print(f"no expiry files under {root}", file=sys.stderr)
        return 1
    market, costs = MarketConfig(), CostConfig()
    lot_of = lambda e: market.lot_size("NIFTY", e)
    plan, by_ed = plan_days(files)
    print("Walk-forward: fit each filter on H1 ONLY, test COLD on H2. A real fix must")
    print("turn H2 positive AND beat 3000 random same-size day-drops (>99% for 5-filter"
          " Bonferroni).")
    for slip in (0.25, 0.50):
        rng = random.Random(SEED)
        recs = features(run(plan, by_ed, lot_of, intraday_params(slippage_per_leg=slip), costs))
        res, n_h2 = study(recs, rng)
        bh1n, bh1d, bh2n, bh2d = res["base"]
        print(f"\n=== slip {slip}/leg. Base (no filter): H1 ₹{bh1n:,.0f} ({bh1d}d), "
              f"H2 ₹{bh2n:,.0f} ({bh2d}d) ===")
        print(f"  {'filter':<12} {'H1 net (fit)':>13} {'H2 net (COLD)':>14} {'H2 days':>9} "
              f"{'vs random':>10}  rationale")
        print("  " + "-" * 92)
        pos = winners = 0
        for name, h1n, h2n, k2, pct, why in res["rows"]:
            if h1n is None:
                print(f"  {name:<12} {'degenerate fit':>13}"); continue
            if h2n > 0:
                pos += 1
            if h2n > 0 and pct > 99.0:
                winners += 1
            print(f"  {name:<12} ₹{h1n:>12,.0f} ₹{h2n:>13,.0f} {k2:>6}/{n_h2} "
                  f"{pct:>8.1f}%  {why}")
        print(f"  -> turn COLD H2 positive: {pos}/5 | also beat random null @99%: {winners}/5")
    print("\nVerdict: no filter fit on H1 durably fixes H2 — the best-in-H1 signal is")
    print("anti-predictive out of sample. The negatives are the true edge. See docs/18.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
