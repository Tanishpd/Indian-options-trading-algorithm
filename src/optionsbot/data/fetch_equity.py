"""Fetch NSE cash-segment EOD into per-symbol daily CSVs for the momentum study.

    python -m optionsbot.data.fetch_equity 2015-01-01 2025-12-31 \
        data/equity/nifty200 --universe config/nifty200_pit.txt

The universe file is one symbol per line. Supply a POINT-IN-TIME membership list
(the Nifty 200 as it stood, not as it stands today) — a current list applied to
history silently drops every stock that fell out of the index, which overstates
a momentum backtest (docs/14). Without --universe, every EQ-series stock is
written, which is a large download.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from .bhavcopy import build_equity_series


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("start", type=date.fromisoformat)
    ap.add_argument("end", type=date.fromisoformat)
    ap.add_argument("out", type=Path, help="output directory for <SYMBOL>.csv")
    ap.add_argument("--universe", type=Path, default=None,
                    help="file of symbols, one per line (point-in-time Nifty 200)")
    args = ap.parse_args(argv)

    symbols = None
    if args.universe:
        symbols = {ln.strip().upper() for ln in args.universe.read_text().splitlines()
                   if ln.strip() and not ln.startswith("#")}
        if not symbols:
            print(f"{args.universe} is empty", file=sys.stderr)
            return 1

    written = build_equity_series(args.start, args.end, args.out, symbols, log=print)
    if not written:
        print("no data written — check the date range and network", file=sys.stderr)
        return 1
    short = {s: n for s, n in written.items() if n < 260}   # < ~1 trading year
    print(f"done: {len(written)} symbols. "
          f"{len(short)} have under a year of history (young listings / thin).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
