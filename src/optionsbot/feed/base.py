"""Live quote feed interface. Feeds provide market DATA only — the paper
loop never places real orders through a feed."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping, Protocol

from ..backtest.data import LegKey


@dataclass(frozen=True)
class Quote:
    ltp: float
    bid: float | None = None
    ask: float | None = None


class QuoteFeed(Protocol):
    def connect(self) -> None: ...

    def reconnect(self) -> None:
        """Re-establish the session after auth/token failure."""
        ...

    def spot(self, index: str) -> float:
        """Index spot LTP."""
        ...

    def list_expiries(self, index: str) -> list[date]:
        """Expiries actually listed by the exchange, sorted ascending —
        the source of truth for expiry selection (holiday-shifted weeks
        diverge from any computed calendar)."""
        ...

    def option_chain(self, index: str, expiry: date, spot: float | None = None) -> Mapping[LegKey, Quote]:
        """Quotes for the chain around spot; pass a pre-fetched spot to avoid
        a duplicate API call."""
        ...

    def lot_size(self, index: str, expiry: date) -> int | None:
        """Lot size per the exchange instrument master (cross-check vs config)."""
        ...
