"""Angel historical fetch — the pure logic, tested with a fake client (the real
API is IP-whitelisted to the box). Token resolution, request windowing, and
response parsing are all pinned; a fake client proves the paging + de-dup.
"""
from datetime import date

from optionsbot.data.angel_history import (
    candle_windows, equity_tokens, fetch_daily, parse_candles)


def test_equity_tokens_keeps_only_nse_eq_series():
    master = [
        {"exch_seg": "NSE", "symbol": "RELIANCE-EQ", "token": "2885"},
        {"exch_seg": "NSE", "symbol": "SOMECO-BE", "token": "9"},      # T2T series
        {"exch_seg": "NFO", "symbol": "RELIANCE25JUL", "token": "111"},  # F&O
        {"exch_seg": "NSE", "symbol": "INFY-EQ", "token": "1594"},
        {"exch_seg": "NSE", "symbol": "NOTWANTED-EQ", "token": "42"},
    ]
    got = equity_tokens(master, {"RELIANCE", "INFY", "SOMECO"})
    assert got == {"RELIANCE": "2885", "INFY": "1594"}   # BE + F&O + unrequested out


def test_candle_windows_pages_a_long_range():
    wins = candle_windows(date(2018, 1, 1), date(2026, 1, 1), max_days=1000)
    assert wins[0][0] == date(2018, 1, 1)
    assert wins[-1][1] == date(2026, 1, 1)
    # contiguous, no gaps or overlaps
    for (a_lo, a_hi), (b_lo, _) in zip(wins, wins[1:]):
        assert (b_lo - a_hi).days == 1
    # each window within the cap
    assert all((hi - lo).days < 1000 for lo, hi in wins)


def test_candle_windows_empty_when_reversed():
    assert candle_windows(date(2026, 1, 1), date(2025, 1, 1)) == []


def test_parse_candles_takes_close_and_skips_junk():
    payload = {"data": [
        ["2024-01-01T00:00:00+05:30", 100, 105, 99, 102.5, 1000],
        ["2024-01-02T00:00:00+05:30", 102, 108, 101, 107.0, 1200],
        ["bad-row"],                                    # malformed -> skipped
    ]}
    assert parse_candles(payload) == [
        (date(2024, 1, 1), 102.5), (date(2024, 1, 2), 107.0)]
    assert parse_candles({}) == []                      # empty/failed response


class FakeClient:
    """Returns a fixed close for every requested day in the window, and records
    how many calls (windows) it was asked for."""

    def __init__(self):
        self.calls = 0

    def getCandleData(self, params):
        self.calls += 1
        lo = date.fromisoformat(params["fromdate"][:10])
        hi = date.fromisoformat(params["todate"][:10])
        data, d = [], lo
        while d <= hi:
            data.append([d.isoformat() + "T00:00:00+05:30", 10, 11, 9, 10.0, 1])
            d = date.fromordinal(d.toordinal() + 1)
        return {"status": True, "data": data}


def test_fetch_daily_pages_and_dedupes():
    c = FakeClient()
    paces = []
    out = fetch_daily(c, "2885", date(2016, 1, 1), date(2024, 12, 31),
                      pace=lambda: paces.append(1))
    assert c.calls >= 2                                 # multi-year -> paged
    assert c.calls == len(paces)                        # paced before each call
    assert out == sorted(out)                           # ascending
    assert out[0][0] == date(2016, 1, 1)
    assert out[-1][0] == date(2024, 12, 31)
    assert len({d for d, _ in out}) == len(out)         # no duplicate dates
