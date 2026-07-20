"""Day-loop backtester.

Flow per trading day: expiry guard -> (if halted: attempt flatten) ->
strategy sees the chain -> limit orders -> conservative fill simulation ->
costs -> end-of-day book risk validation -> mark-to-market -> kill-switch.

Honesty rules built in:
- Positions must be closed by expiry (docs/05 rule 3); the engine refuses to
  fabricate post-expiry marks and raises instead.
- Missing quotes carry the last known mark forward (never reset to entry).
- A tripped switch flattens via simulated limit fills on subsequent days:
  gaps through the band and missing quotes leave positions open — exactly
  the tail risk the drawdown cap exists to measure.
- After each day the book is validated: naked short exposure or a book
  worst-case loss above the per-trade cap trips the kill-switch (docs/01,
  docs/04) through the same alert/halt machinery as a drawdown breach.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Mapping, Protocol, Sequence

from ..config import AppConfig
from ..costs import Fill, ensure_supported_date, fill_costs
from ..fills import limit_fill_price, protection_band_limit
from ..instruments import OptionLeg, Right, Side
from ..metrics import BacktestReport
from ..risk.book import BookLeg, naked_exposure, worst_case_loss
from ..risk.killswitch import KillSwitch
from .data import LegKey, QuoteBar


class EngineError(RuntimeError):
    pass


@dataclass(frozen=True)
class Order:
    leg: OptionLeg
    limit_price: float


@dataclass
class OpenPosition:
    leg: OptionLeg          # leg.side is the position direction
    shares: int
    entry_price: float
    entry_costs: float
    last_mark: float        # last known close; entry price until a bar is seen


@dataclass(frozen=True)
class PositionView:
    """Immutable snapshot handed to strategies — engine state stays private."""
    index: str
    expiry: date
    strike: float
    right: Right
    side: Side
    shares: int
    entry_price: float
    last_mark: float


@dataclass(frozen=True)
class DayContext:
    day: date
    chain: Mapping[LegKey, QuoteBar]
    positions: tuple[PositionView, ...]
    cash: float
    equity: float


class Strategy(Protocol):
    def decide(self, ctx: DayContext) -> Sequence[Order]: ...


def _book_legs(positions: dict[LegKey, OpenPosition]) -> list[BookLeg]:
    return [
        BookLeg(
            index=p.leg.index, expiry=p.leg.expiry, strike=p.leg.strike,
            right=p.leg.right, signed_shares=p.leg.side.sign * p.shares,
            entry_price=p.entry_price,
        )
        for p in positions.values()
    ]


class BacktestEngine:
    def __init__(self, cfg: AppConfig, strategy: Strategy) -> None:
        self.cfg = cfg
        self.strategy = strategy

    def run(self, days: Mapping[date, Mapping[LegKey, QuoteBar]]) -> BacktestReport:
        report = BacktestReport(start_capital=self.cfg.starting_capital)
        switch = KillSwitch(
            self.cfg.risk, alert=None, start_equity=self.cfg.starting_capital
        )
        cash = self.cfg.starting_capital
        positions: dict[LegKey, OpenPosition] = {}

        for day in sorted(days):
            ensure_supported_date(day)
            chain = days[day]
            self._guard_expiries(day, positions)

            if switch.halted:
                cash += self._flatten(day, chain, positions, report)
                equity = cash + self._mark_book(positions, chain)
                report.equity_curve.append((day, equity))
                if not positions:
                    break
                continue

            pre_equity = cash + self._mark_book(positions, chain)
            ctx = DayContext(
                day=day,
                chain=MappingProxyType(dict(chain)),
                positions=tuple(
                    PositionView(
                        index=p.leg.index, expiry=p.leg.expiry, strike=p.leg.strike,
                        right=p.leg.right, side=p.leg.side, shares=p.shares,
                        entry_price=p.entry_price, last_mark=p.last_mark,
                    )
                    for p in positions.values()
                ),
                cash=cash,
                equity=pre_equity,
            )
            filled_any = False
            for order in self.strategy.decide(ctx):
                cash, filled = self._execute(order, day, chain, positions, cash, report)
                filled_any = filled_any or filled

            self._validate_book(positions, switch)

            equity = cash + self._mark_book(positions, chain) if filled_any else pre_equity
            report.equity_curve.append((day, equity))
            switch.update(day, equity)

        report.halted = switch.halted
        report.halt_reason = switch.halt_reason
        report.open_positions_end = len(positions)
        return report

    def _guard_expiries(self, day: date, positions: dict[LegKey, OpenPosition]) -> None:
        for pos in positions.values():
            if day > pos.leg.expiry:
                raise EngineError(
                    f"position {pos.leg.key} held past its {pos.leg.expiry} expiry — "
                    "strategies must square off before expiry (docs/05 rule 3); "
                    "the engine will not fabricate post-expiry marks"
                )

    def _validate_book(self, positions: dict[LegKey, OpenPosition], switch: KillSwitch) -> None:
        legs = _book_legs(positions)
        naked = naked_exposure(legs)
        if naked is not None:
            switch.trip(
                f"naked short exposure in book ({naked}) — defined-risk ban "
                "(docs/01-strategy.md); check wing order limits"
            )
            return
        worst = worst_case_loss(legs)
        cap = self.cfg.risk.per_trade_max_loss_rupees
        if worst > cap:
            switch.trip(
                f"book worst-case loss Rs {worst:,.2f} exceeds per-trade cap "
                f"Rs {cap:,.2f} (docs/04-risk-management.md) — tighten the wings"
            )

    def _mark_book(
        self, positions: dict[LegKey, OpenPosition], chain: Mapping[LegKey, QuoteBar]
    ) -> float:
        """Signed book value at today's marks; carries last known mark when a
        quote is missing (real chains should be complete)."""
        value = 0.0
        for key, pos in positions.items():
            bar = chain.get(key)
            if bar is not None:
                pos.last_mark = bar.close
            value += pos.leg.side.sign * pos.last_mark * pos.shares
        return value

    def _execute(
        self,
        order: Order,
        day: date,
        chain: Mapping[LegKey, QuoteBar],
        positions: dict[LegKey, OpenPosition],
        cash: float,
        report: BacktestReport,
    ) -> tuple[float, bool]:
        bar = chain.get(order.leg.key)
        if bar is None:
            report.unquoted_orders += 1
            return cash, False
        price = limit_fill_price(order.leg.side, order.limit_price, bar)
        if price is None:
            report.unfilled_orders += 1
            return cash, False
        shares = order.leg.lots * self.cfg.market.lot_size(order.leg.index, day)
        return self._settle(order.leg, price, shares, day, positions, report) + cash, True

    def _settle(
        self,
        leg: OptionLeg,
        price: float,
        shares: int,
        day: date,
        positions: dict[LegKey, OpenPosition],
        report: BacktestReport,
    ) -> float:
        """Apply one fill; returns the cash delta. Raises before mutating on
        unsupported flows so a failed order cannot corrupt the report."""
        key = leg.key
        existing = positions.get(key)
        if existing is not None:
            if existing.leg.side is leg.side:
                raise EngineError(
                    f"stacking onto an existing same-side position {key} is not supported "
                    "(docs/04: one defined-risk structure at a time)"
                )
            if existing.shares != shares:
                raise EngineError("partial closes are not supported")

        costs = fill_costs(Fill(day=day, side=leg.side, premium_per_share=price, shares=shares), self.cfg.costs)
        report.total_costs += costs.total
        cash_delta = -leg.side.sign * price * shares - costs.total

        if existing is not None:
            realized = (
                existing.leg.side.sign * (price - existing.entry_price) * shares
                - existing.entry_costs
                - costs.total
            )
            report.trade_pnls.append(realized)
            del positions[key]
        else:
            positions[key] = OpenPosition(
                leg=leg, shares=shares, entry_price=price, entry_costs=costs.total,
                last_mark=price,
            )
        return cash_delta

    def _flatten(
        self,
        day: date,
        chain: Mapping[LegKey, QuoteBar],
        positions: dict[LegKey, OpenPosition],
        report: BacktestReport,
    ) -> float:
        """Kill-switch exit path: simulated limit fills, honest about gaps.

        Exit limits are banded around the PRIOR day's mark and tested against
        today's bar — a gap through the band or a missing quote leaves the
        position open for the next attempt.
        """
        cash_delta = 0.0
        band = self.cfg.fills.protection_band_pct
        for key, pos in list(positions.items()):
            bar = chain.get(key)
            if bar is None:
                report.unquoted_orders += 1
                continue
            exit_side = pos.leg.side.opposite
            limit = protection_band_limit(pos.last_mark, exit_side, band)
            price = limit_fill_price(exit_side, limit, bar)
            if price is None:
                report.unfilled_orders += 1
                continue
            exit_leg = OptionLeg(
                pos.leg.index, pos.leg.expiry, pos.leg.strike, pos.leg.right,
                exit_side, pos.leg.lots,
            )
            cash_delta += self._settle(exit_leg, price, pos.shares, day, positions, report)
        return cash_delta
