"""Backfill the free EOD bhavcopy archive.

    python -m optionsbot.data --index NIFTY --from 2026-07-01 --to 2026-07-17

Writes one CSV per index per day under data/eod/. Days the exchange did not
publish (weekends, holidays, future dates) are skipped, not failed.
"""
from __future__ import annotations

import argparse
import time
from datetime import date
from pathlib import Path

from .bhavcopy import NoDataForDate, daterange, fetch_day, write_csv


def main() -> None:
    ap = argparse.ArgumentParser(description="Download free NSE/BSE EOD option data")
    ap.add_argument("--index", default="NIFTY", choices=["NIFTY", "SENSEX"])
    ap.add_argument("--from", dest="start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--to", dest="end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--out", default="data/eod", help="output directory")
    ap.add_argument("--pause", type=float, default=0.5, help="seconds between requests")
    ap.add_argument("--keep-untraded", action="store_true",
                    help="keep zero-volume rows (their close price is not achievable)")
    args = ap.parse_args()

    out = Path(args.out)
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    got = skipped = existing = 0
    total_rows = 0

    for day in daterange(start, end):
        path = out / args.index / f"{args.index}_{day:%Y%m%d}.csv"
        if path.exists():
            existing += 1
            continue
        try:
            rows = fetch_day(args.index, day, traded_only=not args.keep_untraded)
        except NoDataForDate:
            skipped += 1
            continue
        write_csv(rows, path)
        got += 1
        total_rows += len(rows)
        print(f"{day} {args.index}: {len(rows):>5} rows -> {path}")
        time.sleep(args.pause)

    print(f"\ndone: {got} day(s) downloaded, {existing} already present, "
          f"{skipped} with no data (holiday/weekend), {total_rows:,} rows total")


if __name__ == "__main__":
    main()
