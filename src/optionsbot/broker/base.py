"""Abstract broker adapter.

The real adapter (Kite Connect / SmartAPI / Fyers) is written only after the
PLAN Phase 0 broker decision. Everything upstream depends on this interface,
never on a vendor SDK. Live-regime obligations for implementers (docs/03):
OAuth-only auth with daily token refresh, static whitelisted IP, limit orders
only, and the unfilled-exit ladder from docs/04.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..instruments import OptionLeg


@dataclass(frozen=True)
class OrderResult:
    order_id: str
    fill_price: float | None  # None = unfilled
    reason: str | None = None  # why unfilled: "no_quote" | "limit_not_crossed" | "insufficient_funds"

    def __post_init__(self) -> None:
        if self.fill_price is not None and self.fill_price < 0:
            raise ValueError("fill price cannot be negative")
        if self.fill_price is not None and self.reason is not None:
            raise ValueError("a filled order cannot carry a rejection reason")

    @property
    def filled(self) -> bool:
        return self.fill_price is not None


class Broker(ABC):
    @abstractmethod
    def authenticate(self) -> None: ...

    @abstractmethod
    def quote(self, leg: OptionLeg) -> float:
        """Last traded price for the option."""

    @abstractmethod
    def place_limit_order(self, leg: OptionLeg, limit_price: float, shares: int) -> OrderResult: ...

    @abstractmethod
    def positions(self) -> list[tuple[OptionLeg, int]]:
        """Open positions as (leg, signed shares) — positive long, negative short.

        The signed share count is authoritative for both direction and size;
        the leg's `side` is normalized to match the sign and its `lots` field
        is not meaningful for position sizing.
        """

    @abstractmethod
    def margin_available(self) -> float: ...
