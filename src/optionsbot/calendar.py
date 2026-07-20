"""Weekly expiry calendar and the permitted-universe lock (NIFTY/SENSEX only).

Weekday history:
- SENSEX weeklies expired Friday until Jan 1, 2025 (BSE moved them to Tuesday
  effective that date — verify exact circular before trading this window),
  then Thursday from Sept 1, 2025.
- NIFTY weeklies expired Thursday until the Sept 1, 2025 changeover to Tuesday.
The Sept 2025 changeover is SEBI/exchange-verified; earlier weekdays are widely
documented but were not adversarially verified — re-verify before backtesting
Nov 2024 - Aug 2025.
"""
from __future__ import annotations

from datetime import date, timedelta

SUPPORTED_INDICES = ("NIFTY", "SENSEX")
WEEKDAY_CHANGE = date(2025, 9, 1)
SENSEX_FRIDAY_UNTIL = date(2025, 1, 1)  # exclusive; verify exact BSE changeover

_TUESDAY = 1
_THURSDAY = 3
_FRIDAY = 4


def check_index(index: str) -> None:
    """Universe lock (docs/01): weekly expiries exist only on NIFTY and SENSEX."""
    if index not in SUPPORTED_INDICES:
        raise ValueError(
            f"index {index!r} is outside the permitted universe {SUPPORTED_INDICES} "
            "(docs/01-strategy.md: weekly expiries exist only on NIFTY and SENSEX)"
        )


def expiry_weekday(index: str, on: date) -> int:
    """Scheduled weekly-expiry weekday (Mon=0) for `index` in the regime of date `on`."""
    check_index(index)
    if index == "NIFTY":
        return _TUESDAY if on >= WEEKDAY_CHANGE else _THURSDAY
    if on >= WEEKDAY_CHANGE:
        return _THURSDAY
    return _FRIDAY if on < SENSEX_FRIDAY_UNTIL else _TUESDAY


def _roll_back_for_holidays(expiry: date, holidays: frozenset[date] | set[date]) -> date:
    while expiry in holidays or expiry.weekday() >= 5:
        expiry -= timedelta(days=1)
    return expiry


def next_weekly_expiry(
    index: str, from_date: date, holidays: frozenset[date] | set[date] = frozenset()
) -> date:
    """First weekly expiry on/after `from_date`, holiday-adjusted.

    An expiry falling on a holiday moves to the previous trading day; if that
    moves it before `from_date`, the following week's expiry is returned.
    """
    check_index(index)
    d = from_date
    for _ in range(21):
        if d.weekday() == expiry_weekday(index, d):
            actual = _roll_back_for_holidays(d, holidays)
            if actual >= from_date:
                return actual
        d += timedelta(days=1)
    raise RuntimeError(f"no {index} expiry found within 21 days of {from_date}")
