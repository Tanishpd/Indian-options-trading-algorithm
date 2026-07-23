"""Historical daily candles from Angel One SmartAPI — the long history the free
NSE bhavcopy cannot reach (docs/14).

Free NSE UDiFF equity EOD starts ~2024; a momentum verdict needs history that
spans real drawdowns (2018, 2020, 2022). Angel's `getCandleData` goes back
years further. This module is the pure, testable half — token resolution,
request windowing, response parsing. The authenticated `SmartConnect` client is
injected, because logging in is IP-whitelisted to the EC2 box and enforces one
session per client (so it must run when no live paper session holds the token).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Callable, Iterable

# ONE_DAY candles: Angel caps a single getCandleData call's range. Stay well
# under it and page; 1,900 days keeps a comfortable margin.
_MAX_DAYS_PER_CALL = 1_900


def equity_tokens(master: Iterable[dict], symbols: set[str]) -> dict[str, str]:
    """Map each requested symbol to its NSE cash-segment token.

    Angel lists equities as `<SYMBOL>-EQ` on `exch_seg == "NSE"`. Only the main
    `-EQ` series is returned; `-BE`/`-SM` and other segments are skipped, matching
    the momentum universe (docs/14)."""
    want = {s.upper() for s in symbols}
    out: dict[str, str] = {}
    for row in master:
        if row.get("exch_seg") != "NSE":
            continue
        sym = (row.get("symbol") or "").upper()
        if not sym.endswith("-EQ"):
            continue
        base = sym[:-3]
        if base in want and base not in out:
            out[base] = str(row.get("token"))
    return out


def candle_windows(start: date, end: date,
                   max_days: int = _MAX_DAYS_PER_CALL) -> list[tuple[date, date]]:
    """Split [start, end] into contiguous windows no longer than `max_days`."""
    if start > end:
        return []
    out: list[tuple[date, date]] = []
    lo = start
    while lo <= end:
        hi = min(lo + timedelta(days=max_days - 1), end)
        out.append((lo, hi))
        lo = hi + timedelta(days=1)
    return out


def parse_candles(payload: dict) -> list[tuple[date, float]]:
    """Extract (date, close) from a getCandleData response.

    Angel returns `{"data": [[iso_ts, open, high, low, close, volume], ...]}`.
    A failed/empty response yields nothing rather than raising, so one bad
    window cannot abort a multi-year fetch."""
    rows = (payload or {}).get("data") or []
    out: list[tuple[date, float]] = []
    for r in rows:
        try:
            out.append((date.fromisoformat(str(r[0])[:10]), float(r[4])))
        except (IndexError, ValueError, TypeError):
            continue
    return out


def fetch_daily(client, token: str, start: date, end: date,
                exchange: str = "NSE",
                pace: Callable[[], None] = lambda: None) -> list[tuple[date, float]]:
    """All daily (date, close) for one token, paged across `candle_windows`.

    `client` is an authenticated SmartConnect. `pace` is called before each
    request so the caller can respect Angel's rate limits. De-duplicates on date
    and returns ascending."""
    seen: dict[date, float] = {}
    for lo, hi in candle_windows(start, end):
        pace()
        payload = client.getCandleData({
            "exchange": exchange,
            "symboltoken": token,
            "interval": "ONE_DAY",
            "fromdate": f"{lo.isoformat()} 09:15",
            "todate": f"{hi.isoformat()} 15:30",
        })
        for d, c in parse_candles(payload):
            seen[d] = c
    return sorted(seen.items())
