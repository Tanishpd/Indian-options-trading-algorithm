"""Minute-level option chain data.

Source: a public Kaggle dataset of NIFTY option chains covering the final ten
trading days before each expiry, October 2024 to March 2026. Its authenticity
was verified against official NSE bhavcopy rather than assumed (docs/11):
per-contract daily volume reconciles to the official figure at exactly the lot
size, and the official closing price falls inside the observed intraday range
for every contract tested.

Two properties of the source drive the design here:

1. **30% of minutes carry zero volume.** Those prices are forward-filled, not
   trades — the same value repeats across consecutive minutes. A backtest that
   fills on them is transacting at prices nobody quoted, so `tradeable` is a
   first-class concept and `price` is None when volume is zero.
2. **About 4% of prices sit off the 0.05 tick grid**, implying per-minute
   aggregation rather than a raw last trade. Recorded on the bar so a study can
   decide whether to care; not silently rounded away.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterator

from ..instruments import Right

TICK = 0.05


@dataclass(frozen=True, slots=True)
class Bar:
    """One contract in one minute."""

    ts: datetime
    expiry: date
    strike: float
    right: Right
    ltp: float
    volume: int
    spot: float

    @property
    def tradeable(self) -> bool:
        """False when nothing traded this minute: `ltp` is then a
        forward-filled carry, not a price anyone could have transacted at."""
        return self.volume > 0

    @property
    def price(self) -> float | None:
        """The transactable price, or None if the minute had no trade."""
        return self.ltp if self.tradeable else None

    @property
    def on_tick_grid(self) -> bool:
        return abs(round(self.ltp / TICK) * TICK - self.ltp) < 1e-9

    @property
    def key(self) -> tuple[date, float, Right]:
        return (self.expiry, self.strike, self.right)


FIELDS = ["ts", "expiry", "strike", "right", "ltp", "volume", "spot"]


def write_csv(bars: list[Bar], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(FIELDS)
        for b in bars:
            w.writerow([b.ts.isoformat(sep=" "), b.expiry.isoformat(), b.strike,
                        b.right.value, b.ltp, b.volume, b.spot])


def read_csv(path: Path) -> list[Bar]:
    with open(path, newline="") as fh:
        return [
            Bar(
                ts=datetime.fromisoformat(r["ts"]),
                expiry=date.fromisoformat(r["expiry"]),
                strike=float(r["strike"]),
                right=Right(r["right"]),
                ltp=float(r["ltp"]),
                volume=int(r["volume"]),
                spot=float(r["spot"]),
            )
            for r in csv.DictReader(fh)
        ]


def by_minute(bars: list[Bar]) -> dict[datetime, dict[tuple[date, float, Right], Bar]]:
    """Chain snapshots keyed by minute, then by contract."""
    out: dict[datetime, dict[tuple[date, float, Right], Bar]] = {}
    for b in bars:
        out.setdefault(b.ts, {})[b.key] = b
    return out


def sessions(bars: list[Bar]) -> list[date]:
    return sorted({b.ts.date() for b in bars})


def iter_source(zip_path: Path) -> Iterator[Bar]:
    """Stream the raw Kaggle archive, yielding typed bars.

    Rows whose price or volume cannot be parsed are skipped rather than
    coerced: a silently zeroed price is a fill at a number that never existed.
    """
    import io
    import zipfile

    with zipfile.ZipFile(zip_path) as z:
        name = next(n for n in z.namelist() if n.endswith(".csv"))
        with z.open(name) as fh:
            for row in csv.DictReader(io.TextIOWrapper(fh)):
                try:
                    right = Right(row["option_type"])
                    yield Bar(
                        ts=datetime.fromisoformat(row["timestamp"]),
                        expiry=datetime.fromisoformat(row["expiry"]).date(),
                        strike=float(row["strike_price"]),
                        right=right,
                        ltp=float(row["ltp"]),
                        volume=int(float(row["volume"] or 0)),
                        spot=float(row["underlying_spot_price"]),
                    )
                except (ValueError, KeyError, TypeError):
                    continue
