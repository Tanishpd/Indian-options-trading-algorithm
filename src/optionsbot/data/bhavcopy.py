"""Free NSE and BSE end-of-day F&O bhavcopy (UDiFF format).

Both exchanges publish the identical 34-field UDiFF schema, so one parser
serves NIFTY (NSE) and SENSEX (BSE). Free, no account, no key.

What this data can and cannot do (docs/06):
- CAN validate hold-to-expiry spread economics, strike selection, the cost
  model, lot-size history, and settlement reconciliation.
- CANNOT validate intraday-triggered rules. One row per contract per day
  gives no path: when a day's range contains both the profit target and the
  stop, EOD data cannot say which was touched first, and that ordering
  decides the trade. Backtesting stop-losses needs 1-minute data.

Three traps this module guards against, all confirmed against real files:
1. NSE refuses requests without a browser User-Agent (connection reset).
2. BSE returns HTTP 200 with a ~12.5 KB JavaScript shell for missing dates
   instead of 404 — status codes cannot be trusted, only content.
3. Untraded contracts carry a stale carried-forward `ClsPric` while volume
   and OI are zero. Measured 2026-07-17: 742 of 1,618 NIFTY option rows had
   zero volume, and 100% of those had a non-zero close. One example closed
   at 111.05 against a 54.10 settlement — a 2x error if used as a fill price.
"""
from __future__ import annotations

import csv
import io
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterator

from ..calendar import check_index
from ..costs import ensure_supported_date
from ..instruments import Right

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
NSE_URL = (
    "https://nsearchives.nseindia.com/content/fo/"
    "BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip"
)
BSE_URL = (
    "https://www.bseindia.com/download/Bhavcopy/Derivative/"
    "BhavCopy_BSE_FO_0_0_0_{ymd}_F_0000.CSV"
)
_EXCHANGE_OF = {"NIFTY": "NSE", "SENSEX": "BSE"}

# A BSE miss returns its SPA shell rather than a 404; real files dwarf it.
_MIN_PLAUSIBLE_BYTES = 20_000


class NoDataForDate(Exception):
    """The exchange published nothing for this date (holiday, weekend, future)."""


@dataclass(frozen=True, slots=True)
class EodRow:
    """One contract on one day, from the UDiFF bhavcopy."""

    day: date
    index: str
    expiry: date
    strike: float
    right: Right
    open: float
    high: float
    low: float
    close: float
    last_price: float          # LastPric — survives the expiry-day quirk below
    settlement: float
    underlying: float
    volume: int
    open_interest: int
    lot_size: int

    @property
    def traded(self) -> bool:
        """False when the contract did not trade — `close` is then a stale
        carried-forward number, not a price anyone could have transacted at."""
        return self.volume > 0

    @property
    def _expiry_day_quirk(self) -> bool:
        """On expiry day both exchanges write the settlement INDEX LEVEL into
        SttlmPric, and BSE writes it into ClsPric as well. Confirmed on real
        files: SENSEX 76100CE on 2026-06-18 reported ClsPric and SttlmPric of
        77,409.98 — the index — while LastPric held the true 1,313.70."""
        return self.day == self.expiry

    @property
    def intrinsic(self) -> float:
        """Value at expiry against the settlement index."""
        if self.right is Right.CALL:
            return max(0.0, self.underlying - self.strike)
        return max(0.0, self.strike - self.underlying)

    @property
    def last_traded(self) -> float | None:
        """The last price someone actually transacted at, or None if the
        contract did not trade.

        On expiry day `close` may be the index level rather than an option
        price (BSE always, NSE not observed but not relied upon), so a close
        indistinguishable from the underlying is rejected in favour of
        LastPric, then intrinsic value.
        """
        if not self.traded:
            return None
        if self._expiry_day_quirk and abs(self.close - self.underlying) < 0.01:
            return self.last_price if self.last_price > 0 else self.intrinsic
        return self.close

    @property
    def mark(self) -> float:
        """Valuation basis: settlement price, or intrinsic value on expiry day.

        SttlmPric carries the settlement INDEX LEVEL on expiry day for both
        exchanges, not the option's value — using it directly would value every
        expiring contract at the index. On expiry day an option is worth its
        intrinsic value against that index, which is what is returned.

        Deliberately no single `price` property: the two disagree materially
        often enough that the choice must be made explicitly. Measured
        2026-07-17, across traded rows only, median divergence was 0.00% but
        9% (NIFTY) and 12% (SENSEX) differed by more than 10% — concentrated in
        single-lot trades and deep-ITM strikes, where the last trade is stale
        while settlement reflects end-of-day fair value.
        """
        if self._expiry_day_quirk and abs(self.settlement - self.underlying) < 0.01:
            return self.intrinsic
        return self.settlement

    @property
    def key(self) -> tuple[str, date, float, Right]:
        return (self.index, self.expiry, self.strike, self.right)


def _fetch(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA,                      # NSE refuses requests without one
        "Accept": "*/*",
        "Referer": "https://www.nseindia.com/" if "nseindia" in url
                   else "https://www.bseindia.com/",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise NoDataForDate(f"{url} -> 404") from exc
        raise


def _rows_from_bytes(blob: bytes, url: str) -> list[dict]:
    if blob[:2] == b"PK":                        # NSE ships a zip
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            blob = z.read(z.namelist()[0])
    text = blob.decode("utf-8", errors="replace")
    # BSE answers missing dates with HTTP 200 and a JS shell: trust content,
    # never the status code, or HTML silently becomes market data.
    if len(blob) < _MIN_PLAUSIBLE_BYTES or text.lstrip()[:1] == "<":
        raise NoDataForDate(f"{url} -> {len(blob)} bytes, not a bhavcopy")
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows or "TckrSymb" not in rows[0]:
        raise NoDataForDate(f"{url} -> unexpected schema")
    return rows


def _parse(raw: dict, index: str) -> EodRow | None:
    if raw.get("TckrSymb") != index or raw.get("FinInstrmTp") != "IDO":
        return None                              # not an index option on our symbol
    right = {"CE": Right.CALL, "PE": Right.PUT}.get(raw.get("OptnTp", "").strip())
    if right is None:
        return None                              # futures rows carry no option type
    f = lambda k: float(raw[k] or 0)             # noqa: E731 - terse field reader
    return EodRow(
        day=date.fromisoformat(raw["TradDt"]),
        index=index,
        expiry=date.fromisoformat(raw["XpryDt"]),
        strike=f("StrkPric"),
        right=right,
        open=f("OpnPric"), high=f("HghPric"), low=f("LwPric"), close=f("ClsPric"),
        last_price=f("LastPric"), settlement=f("SttlmPric"), underlying=f("UndrlygPric"),
        volume=int(f("TtlTradgVol")), open_interest=int(f("OpnIntrst")),
        lot_size=int(f("NewBrdLotQty")),
    )


def fetch_day(index: str, day: date, traded_only: bool = True) -> list[EodRow]:
    """All option rows for `index` on `day`.

    `traded_only` (the default) drops untraded contracts, whose close price is
    a stale carried-forward figure rather than an achievable one.
    """
    check_index(index)
    ensure_supported_date(day)                   # docs/06: post-Nov-2024 only
    url = (NSE_URL if _EXCHANGE_OF[index] == "NSE" else BSE_URL).format(
        ymd=day.strftime("%Y%m%d")
    )
    rows = [r for raw in _rows_from_bytes(_fetch(url), url)
            if (r := _parse(raw, index)) is not None]
    if not rows:
        raise NoDataForDate(f"{url} -> no {index} option rows")
    return [r for r in rows if r.traded] if traded_only else rows


FIELDS = [
    "day", "index", "expiry", "strike", "right", "open", "high", "low", "close",
    "last_price", "settlement", "underlying", "volume", "open_interest", "lot_size",
]


def write_csv(rows: list[EodRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(FIELDS)
        for r in rows:
            w.writerow([
                r.day.isoformat(), r.index, r.expiry.isoformat(), r.strike,
                r.right.value, r.open, r.high, r.low, r.close, r.last_price,
                r.settlement, r.underlying, r.volume, r.open_interest, r.lot_size,
            ])


def read_csv(path: Path) -> list[EodRow]:
    with open(path, newline="") as fh:
        return [
            EodRow(
                day=date.fromisoformat(r["day"]), index=r["index"],
                expiry=date.fromisoformat(r["expiry"]), strike=float(r["strike"]),
                right=Right(r["right"]), open=float(r["open"]), high=float(r["high"]),
                low=float(r["low"]), close=float(r["close"]),
                last_price=float(r.get("last_price", 0) or 0),
                settlement=float(r["settlement"]), underlying=float(r["underlying"]),
                volume=int(r["volume"]), open_interest=int(r["open_interest"]),
                lot_size=int(r["lot_size"]),
            )
            for r in csv.DictReader(fh)
        ]


def daterange(start: date, end: date) -> Iterator[date]:
    d = start
    while d <= end:
        if d.weekday() < 5:                      # exchanges are shut at weekends
            yield d
        d += timedelta(days=1)
