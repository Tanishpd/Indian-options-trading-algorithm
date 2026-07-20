from datetime import date

import pytest

from optionsbot.calendar import expiry_weekday, next_weekly_expiry


def test_nifty_thursday_before_sept_2025():
    # Mon 2025-08-25 -> Thu 2025-08-28
    assert next_weekly_expiry("NIFTY", date(2025, 8, 25)) == date(2025, 8, 28)


def test_nifty_tuesday_from_sept_2025():
    # Mon 2025-09-01 -> Tue 2025-09-02
    assert next_weekly_expiry("NIFTY", date(2025, 9, 1)) == date(2025, 9, 2)


def test_sensex_swaps_to_thursday():
    assert expiry_weekday("SENSEX", date(2025, 8, 1)) == 1  # Tuesday
    assert expiry_weekday("SENSEX", date(2025, 9, 1)) == 3  # Thursday


def test_sensex_was_friday_before_2025():
    assert expiry_weekday("SENSEX", date(2024, 11, 6)) == 4  # Friday
    assert next_weekly_expiry("SENSEX", date(2024, 11, 6)) == date(2024, 11, 8)


def test_changeover_gap_is_handled():
    # Fri 2025-08-29: remaining pre-change days have no Thursday; the first
    # post-change NIFTY expiry is Tue 2025-09-02.
    assert next_weekly_expiry("NIFTY", date(2025, 8, 29)) == date(2025, 9, 2)


def test_holiday_rolls_back_to_previous_trading_day():
    holidays = {date(2025, 9, 2)}
    assert next_weekly_expiry("NIFTY", date(2025, 9, 1), holidays) == date(2025, 9, 1)


def test_holiday_rollback_before_from_date_skips_to_next_week():
    holidays = {date(2025, 9, 2)}
    # From the (holiday) expiry day itself: rolled-back Monday is in the past.
    assert next_weekly_expiry("NIFTY", date(2025, 9, 2), holidays) == date(2025, 9, 9)


def test_universe_is_locked():
    with pytest.raises(ValueError, match="permitted universe"):
        next_weekly_expiry("BANKNIFTY", date(2026, 7, 1))
