from datetime import date

import pytest

from optionsbot.backtest.data import QuoteBar, by_day, load_csv
from optionsbot.instruments import Right

CSV_OK = """day,index,expiry,strike,right,open,high,low,close
2026-07-07,NIFTY,2026-07-14,25900,CE,62.0,66.5,58.0,60.0
2026-07-07,NIFTY,2026-07-14,25100,PE,54.0,57.0,52.0,55.0
2026-07-08,NIFTY,2026-07-14,25900,CE,12.0,14.0,9.0,10.0
"""

CSV_STALE = """day,index,expiry,strike,right,open,high,low,close
2024-06-03,NIFTY,2024-06-06,23000,CE,62.0,66.5,58.0,60.0
"""


def test_load_csv_roundtrip(tmp_path):
    p = tmp_path / "quotes.csv"
    p.write_text(CSV_OK)
    bars = load_csv(p)
    assert len(bars) == 3
    assert bars[0].right is Right.CALL
    assert bars[0].close == 60.0

    days = by_day(bars)
    assert set(days) == {date(2026, 7, 7), date(2026, 7, 8)}
    assert len(days[date(2026, 7, 7)]) == 2


def test_loader_rejects_pre_nov_2024_data(tmp_path):
    p = tmp_path / "stale.csv"
    p.write_text(CSV_STALE)
    with pytest.raises(ValueError, match="pre-Nov-2024"):
        load_csv(p)


def test_loader_reports_file_and_line_on_bad_rows(tmp_path):
    p = tmp_path / "trunc.csv"
    p.write_text(
        "day,index,expiry,strike,right,open,high,low,close\n"
        "2026-07-07,NIFTY,2026-07-14,25900,CE,62.0,66.5,58.0\n"  # missing close
    )
    with pytest.raises(ValueError, match="line 2"):
        load_csv(p)


def test_by_day_rejects_duplicate_quotes(tmp_path):
    p = tmp_path / "dupe.csv"
    p.write_text(
        "day,index,expiry,strike,right,open,high,low,close\n"
        "2026-07-07,NIFTY,2026-07-14,25900,CE,62.0,66.5,58.0,60.0\n"
        "2026-07-07,NIFTY,2026-07-14,25900,CE,12.0,14.0,9.0,10.0\n"
    )
    with pytest.raises(ValueError, match="duplicate quote"):
        by_day(load_csv(p))


def test_loader_rejects_out_of_universe_index(tmp_path):
    p = tmp_path / "bank.csv"
    p.write_text(
        "day,index,expiry,strike,right,open,high,low,close\n"
        "2026-07-07,BANKNIFTY,2026-07-14,50000,CE,62.0,66.5,58.0,60.0\n"
    )
    with pytest.raises(ValueError, match="permitted universe"):
        load_csv(p)
