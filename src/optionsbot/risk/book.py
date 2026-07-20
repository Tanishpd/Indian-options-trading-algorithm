"""Book-level risk checks shared by the backtest engine and the paper loop.

One home for the two invariants every execution path must enforce (docs/01,
docs/04): no naked short exposure, and book worst-case loss within the
per-trade cap. Both operate on signed share counts with entry basis, so they
are lot-size agnostic and identical across backtest and paper.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..instruments import Right


@dataclass(frozen=True)
class BookLeg:
    index: str
    expiry: date
    strike: float
    right: Right
    signed_shares: int   # positive long, negative short
    entry_price: float


def naked_exposure(legs: list[BookLeg]) -> str | None:
    """Name the first (index, expiry, right) group with net short shares, if any."""
    nets: dict[tuple[str, date, Right], int] = {}
    for leg in legs:
        k = (leg.index, leg.expiry, leg.right)
        nets[k] = nets.get(k, 0) + leg.signed_shares
    for (index, expiry, right), net in nets.items():
        if net < 0:
            return f"{index} {expiry} {right.name} net {net} shares"
    return None


def _intrinsic(right: Right, strike: float, underlying: float) -> float:
    if right is Right.CALL:
        return max(0.0, underlying - strike)
    return max(0.0, strike - underlying)


def worst_case_loss(legs: list[BookLeg]) -> float:
    """Worst-case expiry loss of the whole book in rupees, vs entry basis.

    Grouped by (index, expiry): one underlying price per group; groups summed
    conservatively (each can realise its own worst case). Piecewise-linear
    payoff => the minimum sits at a strike vertex or a tail.
    """
    groups: dict[tuple[str, date], list[BookLeg]] = {}
    for leg in legs:
        groups.setdefault((leg.index, leg.expiry), []).append(leg)

    total_worst = 0.0
    for group in groups.values():
        strikes = sorted({l.strike for l in group})
        candidates = [0.0, *strikes, strikes[-1] * 2]
        worst = min(
            sum(
                (_intrinsic(l.right, l.strike, s) - l.entry_price) * l.signed_shares
                for l in group
            )
            for s in candidates
        )
        total_worst += min(0.0, worst)
    return -total_worst
