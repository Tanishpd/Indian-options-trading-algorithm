"""Option quote data: schema, CSV loader, and day-grouping.

CSV schema (one row per option per day):
    day,index,expiry,strike,right,open,high,low,close
    2026-07-07,NIFTY,2026-07-14,25900,CE,62.0,66.5,58.0,60.0

The loader refuses pre-Nov-2024 rows and out-of-universe indices; by_day
refuses duplicate keys (merged/doubled files corrupt quotes silently otherwise).
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from ..calendar import check_index
from ..costs import MIN_SUPPORTED_DATE
from ..instruments import Right

LegKey = tuple[str, date, float, Right]


@lru_cache(maxsize=4096)
def _parse_date(s: str) -> date:
    # Real datasets repeat a few hundred distinct date strings millions of times.
    return date.fromisoformat(s)


@dataclass(frozen=True, slots=True)
class QuoteBar:
    day: date
    index: str
    expiry: date
    strike: float
    right: Right
    open: float
    high: float
    low: float
    close: float

    def __post_init__(self) -> None:
        check_index(self.index)
        object.__setattr__(self, "right", Right(self.right))
        if not (self.low <= self.open <= self.high and self.low <= self.close <= self.high):
            raise ValueError(f"inconsistent OHLC on {self.day} {self.strike} {self.right}")
        if self.low < 0:
            raise ValueError("negative price")

    @property
    def key(self) -> LegKey:
        return (self.index, self.expiry, self.strike, self.right)


def load_csv(path: str | Path) -> list[QuoteBar]:
    bars: list[QuoteBar] = []
    with open(path, newline="") as f:
        for lineno, row in enumerate(csv.DictReader(f), start=2):
            try:
                day = _parse_date(row["day"])
                if day < MIN_SUPPORTED_DATE:
                    raise ValueError(
                        f"row dated {day} is before {MIN_SUPPORTED_DATE} — "
                        "pre-Nov-2024 data is banned from backtests (docs/06)"
                    )
                bars.append(
                    QuoteBar(
                        day=day,
                        index=row["index"],
                        expiry=_parse_date(row["expiry"]),
                        strike=float(row["strike"]),
                        right=Right(row["right"]),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"{path}, line {lineno}: {exc}") from exc
    return bars


def by_day(bars: list[QuoteBar]) -> dict[date, dict[LegKey, QuoteBar]]:
    days: dict[date, dict[LegKey, QuoteBar]] = {}
    for bar in bars:
        chain = days.setdefault(bar.day, {})
        if bar.key in chain:
            raise ValueError(
                f"duplicate quote for {bar.key} on {bar.day} — "
                "merged or doubled data files corrupt backtests silently"
            )
        chain[bar.key] = bar
    return days
