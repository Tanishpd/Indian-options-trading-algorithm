"""Run the momentum backtest over a directory of per-symbol daily CSVs.

    python -m optionsbot.research.run_momentum data/equity/nifty200 \
        --index data/equity/index/NIFTY50.csv --capital 500000

Each file is `<SYMBOL>.csv` with a `date,close` header (extra columns ignored).
The --index file is the regime-filter benchmark (Nifty 50 or Nifty 200 daily
close). Supply a POINT-IN-TIME membership universe if you have one; a current
Nifty 200 list applied to history is survivorship bias and overstates the result
(docs/14).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..data.equity import read_dir, read_series
from .momentum import EquityCostConfig, MomentumParams, backtest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("universe", type=Path, help="dir of <SYMBOL>.csv daily files")
    ap.add_argument("--index", type=Path, default=None,
                    help="benchmark CSV for the 200-DMA regime filter")
    ap.add_argument("--capital", type=float, default=500_000.0)
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--no-regime", action="store_true",
                    help="disable the 200-DMA cash filter (shows the raw drawdown)")
    ap.add_argument("--membership", type=Path, default=None,
                    help="dir of YYYY-MM-DD.txt index snapshots (point-in-time "
                         "universe — removes survivorship bias; docs/14)")
    args = ap.parse_args(argv)

    series = read_dir(args.universe)
    if not series:
        print(f"no <SYMBOL>.csv files under {args.universe}", file=sys.stderr)
        return 1
    index = read_series(args.index) if args.index else None

    membership = load_membership(args.membership) if args.membership else None
    params = MomentumParams(top_n=args.top, use_regime_filter=not args.no_regime)
    res = backtest(series, index, params, EquityCostConfig(), args.capital,
                   membership=membership)

    if not res.equity_curve:
        print("no trading days in the supplied data", file=sys.stderr)
        return 1

    start_d, end_d = res.equity_curve[0][0], res.equity_curve[-1][0]
    pit = "point-in-time index" if membership else "FIXED universe (survivorship-biased)"
    print(f"universe {len(series)} symbols [{pit}]  |  {start_d} .. {end_d}  "
          f"({res.years:.1f} yr)  |  regime filter "
          f"{'ON' if params.use_regime_filter else 'OFF'}")
    print(f"  start        Rs {res.start_capital:>12,.0f}")
    print(f"  end          Rs {res.end_equity:>12,.0f}")
    print(f"  CAGR         {res.cagr_pct:>8.2f}% / yr")
    print(f"  max drawdown {res.max_drawdown_pct:>8.2f}%  "
          f"<- the number a capital-preservation mandate lives or dies on")
    print(f"  Sharpe       {res.sharpe:>8.2f}")
    print(f"  costs paid   Rs {res.costs_paid:>12,.0f}  "
          f"({100 * res.costs_paid / res.start_capital:.1f}% of capital, "
          f"avg turnover {res.avg_turnover_pct:.0f}%/rebalance)")
    print(f"  rebalances   {res.rebalances}  "
          f"({res.in_cash_rebalances} in cash on the regime filter)")
    print("\n  NOTE: this is GROSS of STCG tax. Short-term equity gains are taxed "
          "at\n  the prevailing rate (15% historically); apply that haircut to "
          "the CAGR\n  for a net-of-tax figure. And the verdict is only as honest "
          "as the\n  universe: a current membership list applied to history is "
          "survivorship bias.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
