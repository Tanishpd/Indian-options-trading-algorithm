"""Daily equity price series — the data a momentum strategy consumes.

The rest of this project trades options; momentum trades stocks (docs/14). The
two need different data: options need per-contract chains, momentum needs one
daily close per stock over a long history. This module is that second shape.

A `Series` is one symbol's dated closes, sorted ascending, with the lookback and
volatility helpers the momentum score is built from. Nothing here fetches data —
supply a directory of per-symbol CSVs (see `read_dir`), or extend
`optionsbot.data.bhavcopy` to pull the NSE cash-segment EOD bhavcopy, which
carries daily OHLCV for every listed stock.
"""
from __future__ import annotations

import csv
import statistics
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Series:
    """One symbol's daily closes, oldest first."""

    symbol: str
    dates: tuple[date, ...]
    closes: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.dates) != len(self.closes):
            raise ValueError(f"{self.symbol}: dates/closes length mismatch")
        if list(self.dates) != sorted(self.dates):
            raise ValueError(f"{self.symbol}: dates must be ascending")

    def index_on_or_before(self, day: date) -> int | None:
        """Position of the last bar at or before `day`, or None if none exists."""
        lo, hi, out = 0, len(self.dates) - 1, None
        while lo <= hi:
            mid = (lo + hi) // 2
            if self.dates[mid] <= day:
                out, lo = mid, mid + 1
            else:
                hi = mid - 1
        return out

    def lookback_return(self, i: int, span: int) -> float | None:
        """Simple return from `span` bars before index i to i. None if too short."""
        j = i - span
        if j < 0 or self.closes[j] <= 0:
            return None
        return self.closes[i] / self.closes[j] - 1.0

    def daily_vol(self, i: int, span: int) -> float | None:
        """Sample stdev of the last `span` daily returns ending at index i."""
        if i - span < 0:
            return None
        rets = [
            self.closes[k] / self.closes[k - 1] - 1.0
            for k in range(i - span + 1, i + 1)
            if self.closes[k - 1] > 0
        ]
        if len(rets) < 2:
            return None
        return statistics.stdev(rets)


def read_series(path: Path, symbol: str | None = None) -> Series:
    """One CSV of `date,close` (extra columns ignored) -> a Series."""
    sym = symbol or Path(path).stem
    rows: list[tuple[date, float]] = []
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                rows.append((date.fromisoformat(r["date"]), float(r["close"])))
            except (KeyError, ValueError):
                continue                       # skip unparseable rows, never coerce
    rows.sort()
    return Series(symbol=sym, dates=tuple(d for d, _ in rows),
                  closes=tuple(c for _, c in rows))


def read_dir(root: Path) -> dict[str, Series]:
    """Every `<SYMBOL>.csv` under `root`, keyed by symbol."""
    root = Path(root)
    out: dict[str, Series] = {}
    for path in sorted(root.glob("*.csv")):
        s = read_series(path)
        if s.dates:
            out[s.symbol] = s
    return out


def trading_days(series: dict[str, Series]) -> list[date]:
    """The union of all symbols' dates, ascending — the backtest's clock."""
    days: set[date] = set()
    for s in series.values():
        days.update(s.dates)
    return sorted(days)


def load_membership(root: Path) -> list[tuple[date, frozenset[str]]]:
    """Point-in-time index membership from dated snapshot files.

    Each file is named `YYYY-MM-DD.txt` (the effective date of a reconstitution)
    and lists that snapshot's member symbols, one per line (`#` comments and
    blanks ignored). The index reconstitutes semi-annually, so ~2 files per year
    is enough. Returned ascending by date — the shape `momentum.backtest`'s
    `membership` argument expects. This is what converts the momentum backtest
    from a survivorship-biased ceiling into an honest verdict (docs/14)."""
    root = Path(root)
    out: list[tuple[date, frozenset[str]]] = []
    for path in sorted(root.glob("*.txt")):
        try:
            eff = date.fromisoformat(path.stem)
        except ValueError:
            continue                            # not a dated snapshot file
        members = frozenset(
            ln.strip().upper() for ln in path.read_text().splitlines()
            if ln.strip() and not ln.startswith("#")
        )
        if members:
            out.append((eff, members))
    out.sort()
    return out


def month_end_days(days: list[date]) -> list[date]:
    """The last trading day in each calendar month — the rebalance dates."""
    out: list[date] = []
    for i, d in enumerate(days):
        last = i == len(days) - 1
        if last or (days[i + 1].year, days[i + 1].month) != (d.year, d.month):
            out.append(d)
    return out
