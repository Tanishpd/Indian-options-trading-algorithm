"""Option legs and defined-risk structures.

The docs/01 ban on naked selling is enforced structurally: a Structure whose
short legs are not fully covered by long legs (per index/expiry/right group)
cannot be constructed. The backtest engine additionally validates the live
book after every trading day, so the ban holds on the execution path too.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from .calendar import check_index


class Right(str, Enum):
    CALL = "CE"
    PUT = "PE"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def sign(self) -> int:
        """+1 for BUY, -1 for SELL — the one place this convention is defined."""
        return 1 if self is Side.BUY else -1

    @property
    def opposite(self) -> "Side":
        return Side.SELL if self is Side.BUY else Side.BUY


@dataclass(frozen=True)
class OptionLeg:
    index: str
    expiry: date
    strike: float
    right: Right
    side: Side
    lots: int = 1

    def __post_init__(self) -> None:
        check_index(self.index)
        # Coerce "CE"/"BUY"-style strings into enum members: str-mixin enums
        # pass ==/hash checks but fail the `is` dispatch used downstream.
        object.__setattr__(self, "right", Right(self.right))
        object.__setattr__(self, "side", Side(self.side))
        if not isinstance(self.expiry, date) or type(self.expiry) is not date:
            raise TypeError("expiry must be a datetime.date (not datetime) — chain keys compare by exact type")
        if self.lots < 1:
            raise ValueError("lots must be >= 1")
        if self.strike <= 0:
            raise ValueError("strike must be positive")

    @property
    def key(self) -> tuple[str, date, float, Right]:
        return (self.index, self.expiry, self.strike, self.right)


def _validate_defined_risk(legs: tuple[OptionLeg, ...]) -> None:
    """Every (index, expiry, right) group must have long lots >= short lots.

    Equal-or-greater long coverage bounds the expiry payoff on both tails
    (slope beyond the outermost strike is (longs - shorts) <= 0 loss-side),
    so max loss is finite regardless of strike placement.
    """
    groups: dict[tuple[str, date, Right], dict[Side, int]] = {}
    for leg in legs:
        g = groups.setdefault((leg.index, leg.expiry, leg.right), {Side.BUY: 0, Side.SELL: 0})
        g[leg.side] += leg.lots
    for (index, expiry, right), counts in groups.items():
        if counts[Side.SELL] > counts[Side.BUY]:
            raise ValueError(
                f"naked short exposure in {index} {expiry} {right.name}: "
                f"{counts[Side.SELL]} short lots vs {counts[Side.BUY]} long lots — "
                "naked selling is banned (docs/01-strategy.md)"
            )


@dataclass(frozen=True)
class Structure:
    name: str
    legs: tuple[OptionLeg, ...]

    def __post_init__(self) -> None:
        if not self.legs:
            raise ValueError("structure needs at least one leg")
        _validate_defined_risk(self.legs)


def credit_spread(
    index: str, expiry: date, right: Right, short_strike: float, long_strike: float, lots: int = 1
) -> Structure:
    if right is Right.CALL and long_strike <= short_strike:
        raise ValueError("call credit spread needs long strike above short strike")
    if right is Right.PUT and long_strike >= short_strike:
        raise ValueError("put credit spread needs long strike below short strike")
    return Structure(
        name=f"{right.name.lower()}_credit_spread",
        legs=(
            OptionLeg(index, expiry, short_strike, right, Side.SELL, lots),
            OptionLeg(index, expiry, long_strike, right, Side.BUY, lots),
        ),
    )


def iron_condor(
    index: str,
    expiry: date,
    short_call: float,
    long_call: float,
    short_put: float,
    long_put: float,
    lots: int = 1,
) -> Structure:
    if not (long_put < short_put < short_call < long_call):
        raise ValueError(
            "iron condor needs long_put < short_put < short_call < long_call"
        )
    return Structure(
        name="iron_condor",
        legs=(
            OptionLeg(index, expiry, short_call, Right.CALL, Side.SELL, lots),
            OptionLeg(index, expiry, long_call, Right.CALL, Side.BUY, lots),
            OptionLeg(index, expiry, short_put, Right.PUT, Side.SELL, lots),
            OptionLeg(index, expiry, long_put, Right.PUT, Side.BUY, lots),
        ),
    )


def _intrinsic(leg: OptionLeg, underlying: float) -> float:
    if leg.right is Right.CALL:
        return max(0.0, underlying - leg.strike)
    return max(0.0, leg.strike - underlying)


def _group_worst_payoff(legs: list[OptionLeg]) -> float:
    """Worst expiry payoff per share for legs sharing one underlying+expiry.

    Piecewise linear in the underlying, so the minimum sits at a strike
    vertex or a tail; never counted better than zero so a profitable group
    cannot offset another group's loss.
    """
    strikes = sorted({leg.strike for leg in legs})
    candidates = [0.0, *strikes, strikes[-1] * 2]
    worst = min(
        sum(leg.side.sign * _intrinsic(leg, s) * leg.lots for leg in legs)
        for s in candidates
    )
    return min(0.0, worst)


def max_loss(structure: Structure, net_credit_per_share: float, lot_size: int) -> float:
    """Worst-case loss in rupees at expiry.

    `net_credit_per_share` is the signed premium sum per share across ALL
    legs including their lots multipliers (credit positive, debit negative).
    Legs are grouped by (index, expiry): each group shares one underlying
    price, while distinct groups can each realise their own worst case
    (conservative sum). Assumes a uniform lot size across legs — for
    mixed-index books use the engine's share-based book check instead.
    """
    groups: dict[tuple[str, date], list[OptionLeg]] = {}
    for leg in structure.legs:
        groups.setdefault((leg.index, leg.expiry), []).append(leg)
    worst_payoff = sum(_group_worst_payoff(legs) for legs in groups.values())
    return max(0.0, -(worst_payoff + net_credit_per_share)) * lot_size


def assert_within_per_trade_cap(
    structure: Structure, net_credit_per_share: float, lot_size: int, cap_rupees: float
) -> None:
    loss = max_loss(structure, net_credit_per_share, lot_size)
    if loss > cap_rupees:
        raise ValueError(
            f"{structure.name} max loss Rs {loss:,.2f} exceeds per-trade cap "
            f"Rs {cap_rupees:,.2f} (docs/04-risk-management.md) — tighten the wings"
        )
