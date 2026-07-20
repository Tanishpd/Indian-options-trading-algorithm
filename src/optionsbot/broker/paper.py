"""In-memory paper broker for dry runs and Phase 5 wiring.

Matches the project's conservative execution model: fills at the LIMIT price
(never better, mirroring fills.py), charges full transaction costs by default
(a costless paper record is the fiction docs/05 bans), rejects orders the
account cannot cash-settle, and tracks per-position entry basis so book-level
risk checks (risk/book.py) are computable in paper.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from itertools import count

from ..config import CostConfig
from ..costs import Fill, fill_costs
from ..instruments import OptionLeg, Side
from .base import Broker, OrderResult


@dataclass(frozen=True)
class BookPosition:
    leg: OptionLeg       # side normalized to the sign of net
    net: int             # signed shares: positive long, negative short
    entry_price: float   # volume-weighted average entry


class PaperBroker(Broker):
    def __init__(self, cash: float, costs: CostConfig | None = None) -> None:
        """`costs=None` uses default CostConfig — pass an explicit zeroed
        CostConfig only for arithmetic-transparent tests."""
        self._cash = cash
        self._costs = CostConfig() if costs is None else costs
        self.today: date | None = None  # must be set before trading (STT is date-dependent)
        self._quotes: dict[tuple, float] = {}
        self._net: dict[tuple, int] = {}
        self._avg: dict[tuple, float] = {}
        self._ref_leg: dict[tuple, OptionLeg] = {}
        self._ids = count(1)
        self._authenticated = False

    def set_quote(self, leg: OptionLeg, price: float) -> None:
        self._quotes[leg.key] = price

    def set_quotes(self, quotes: dict) -> None:
        """Bulk update keyed by LegKey — the paper loop feeds live LTPs here."""
        self._quotes.update(quotes)

    def authenticate(self) -> None:
        self._authenticated = True

    def quote(self, leg: OptionLeg) -> float:
        return self._quotes[leg.key]

    def place_limit_order(self, leg: OptionLeg, limit_price: float, shares: int) -> OrderResult:
        if not self._authenticated:
            raise RuntimeError("authenticate() before trading")
        if self.today is None:
            raise RuntimeError("set PaperBroker.today before trading (costs are date-dependent)")

        order_id = str(next(self._ids))
        market = self._quotes.get(leg.key)
        if market is None:
            return OrderResult(order_id=order_id, fill_price=None, reason="no_quote")
        crossed = market <= limit_price if leg.side is Side.BUY else market >= limit_price
        if not crossed:
            return OrderResult(order_id=order_id, fill_price=None, reason="limit_not_crossed")

        # Conservative fill at the limit, never at the (better) market price.
        price = limit_price
        cost = fill_costs(
            Fill(day=self.today, side=leg.side, premium_per_share=price, shares=shares),
            self._costs,
        ).total
        cash_delta = -leg.side.sign * price * shares - cost
        if self._cash + cash_delta < 0:
            return OrderResult(order_id=order_id, fill_price=None, reason="insufficient_funds")

        self._cash += cash_delta
        self._apply(leg, price, leg.side.sign * shares)
        return OrderResult(order_id=order_id, fill_price=price)

    def _apply(self, leg: OptionLeg, price: float, signed: int) -> None:
        key = leg.key
        held = self._net.get(key, 0)
        net = held + signed
        if net == 0:
            self._net.pop(key, None)
            self._avg.pop(key, None)
            self._ref_leg.pop(key, None)
            return
        if held == 0 or (held > 0) != (net > 0):
            self._avg[key] = price            # fresh position or flip through zero
        elif abs(net) > abs(held):            # adding to the same side: weighted avg
            self._avg[key] = (self._avg[key] * abs(held) + price * abs(signed)) / abs(net)
        # reducing without flipping keeps the existing basis
        self._net[key] = net
        self._ref_leg[key] = leg

    def positions(self) -> list[tuple[OptionLeg, int]]:
        return [(p.leg, p.net) for p in self.book()]

    def book(self) -> list[BookPosition]:
        """Positions with entry basis — side normalized to the sign of net."""
        out: list[BookPosition] = []
        for key, net in self._net.items():
            leg = replace(self._ref_leg[key], side=Side.BUY if net > 0 else Side.SELL)
            out.append(BookPosition(leg=leg, net=net, entry_price=self._avg[key]))
        return out

    def margin_available(self) -> float:
        return self._cash

    def snapshot(self) -> dict:
        """Serializable state for session persistence."""
        return {
            "cash": self._cash,
            "positions": [
                {
                    "index": p.leg.index, "expiry": p.leg.expiry.isoformat(),
                    "strike": p.leg.strike, "right": p.leg.right.value,
                    "side": p.leg.side.value, "lots": p.leg.lots,
                    "net": p.net, "entry_price": p.entry_price,
                }
                for p in self.book()
            ],
        }

    def restore(self, state: dict) -> None:
        self._cash = state["cash"]
        self._net.clear()
        self._avg.clear()
        self._ref_leg.clear()
        for p in state["positions"]:
            leg = OptionLeg(
                p["index"], date.fromisoformat(p["expiry"]), p["strike"],
                p["right"], p["side"], p["lots"],
            )
            self._net[leg.key] = p["net"]
            self._avg[leg.key] = p.get("entry_price", 0.0)
            self._ref_leg[leg.key] = leg
